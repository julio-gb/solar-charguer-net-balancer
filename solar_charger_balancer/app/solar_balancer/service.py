"""Orquestación: lectura de HA, balance horario, decisiones, cargador y publicación MQTT."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .charger import Charger, ChargerEntities, ChargerReadings
from .config import Config
from .controller import ControlInputs, ControlParams, decide, minutes_left_in_hour
from .energy import CounterTracker, HourRecord, compute_stats
from .forced import ForcedCharge, ScheduleError, parse_start
from .ha_client import HAClient, HAError, is_available, to_float
from .soc import SocEstimator
from .storage import save_state
from .tariff import Tariff

_LOGGER = logging.getLogger(__name__)
VERSION = "0.4.3"
KEEP_DAYS = 400
TRACE_LEN = 2500
NOTIFICATION_ID = "solar_charger_balancer_offline"


def _stamp(state: dict | None) -> datetime | None:
    """Momento en que el sensor reportó por última vez."""
    if not state:
        return None
    raw = state.get("last_reported") or state.get("last_updated")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _raw_stamp(state: dict | None) -> str | None:
    if not state:
        return None
    return f"{state.get('state')}@{state.get('last_updated', '')[11:19]}"


def hour_start(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


class Balancer:
    def __init__(self, config: Config, ha: HAClient, tz: ZoneInfo, publisher=None):
        self.cfg = config
        self.ha = ha
        self.tz = tz
        self.pub = publisher  # MqttBridge o None (tests)
        self.tariff = Tariff(config)
        self.params = ControlParams(
            voltage=config.voltage, min_current=config.min_current, max_current=config.max_current,
            decision_interval_min=config.decision_interval_minutes, end_window_min=config.end_of_hour_window_minutes,
            margin_wh=config.safety_margin_wh, min_on_min=config.min_on_minutes, min_off_min=config.min_off_minutes,
            strategy=config.strategy, surplus_factor=config.surplus_factor,
        )
        self.charger = Charger(ha, ChargerEntities(
            start=config.charger_start_entity, current=config.charger_current_entity,
            stop=config.charger_stop_entity, current_apply=config.charger_current_apply_entity,
            current_readback=config.charger_current_readback_entity, state=config.charger_state_entity,
            charging_states=config.charger_charging_states, unplugged_states=config.charger_unplugged_states))
        self.counters = {k: CounterTracker() for k in ("gen", "home", "ev")}
        self.records: list[HourRecord] = []
        self.hour: datetime | None = None
        self.acc = {"gen": 0.0, "home": 0.0, "ev": 0.0}
        # Hora anterior aún abierta durante unos minutos para recibir la energía que los
        # sensores (FusionSolar, cada ~5 min) reportan con retraso.
        self.prev: dict | None = None
        self.stamps: dict[str, datetime | None] = {"gen": None, "home": None, "ev": None}
        self.ev_total = 0.0
        self.powers: dict[str, float | None] = {"gen": None, "home": None, "ev": None}
        self.workday_override: bool | None = None
        self.enabled = True
        self.forced: ForcedCharge | None = None
        self.forced_inputs = {"start": "00:00", "hours": 4.0, "current": config.max_current}
        self.forced_message = "Sin carga programada"
        self.soc = SocEstimator(config.car_battery_kwh, config.charging_efficiency)
        self.last_switch: datetime | None = None
        self.last_decision_at: datetime | None = None
        self.decision = None
        self.mode = "Iniciando"
        self.events: deque[dict] = deque(maxlen=30)
        # Traza de diagnóstico: una entrada por decisión u orden enviada (≈ 7 días).
        self.trace: deque[dict] = deque(maxlen=TRACE_LEN)
        self._stamps_raw: dict[str, str | None] = {}
        self.notified_offline = False
        self.offline_logged = False
        self._decided = False
        self._ev_power_prev: tuple[datetime, float] | None = None  # (momento, kW) de la lectura anterior
        self.wake = asyncio.Event()

    # ------------------------------------------------------------------ estado
    def restore(self, data: dict, now: datetime) -> None:
        self.records = [HourRecord.from_dict(r) for r in data.get("records", [])]
        self.enabled = data.get("enabled", True)
        self.forced_inputs.update(data.get("forced_inputs", {}))
        if data.get("forced"):
            self.forced = ForcedCharge.from_dict(data["forced"])
            self.forced_message = f"Programada: {self.forced.describe()}"
        self.soc.load(data.get("soc", {}))
        self.ev_total = data.get("ev_total", 0.0)
        for item in data.get("trace", []):
            self.trace.append(item)
        for event in data.get("events", []):
            self.events.append(event)
        if data.get("prev"):
            self._close_hour(datetime.fromisoformat(data["prev"]["hour"]), data["prev"]["acc"])
        saved_hour = data.get("hour")
        if saved_hour and datetime.fromisoformat(saved_hour) == hour_start(now):
            self.hour = datetime.fromisoformat(saved_hour)
            self.acc.update(data.get("acc", {}))
            for key, last in data.get("counters", {}).items():
                self.counters[key].last = last
        elif saved_hour:
            # La hora guardada ya terminó: se cierra tal cual y se toman referencias nuevas
            # para no atribuir a la hora actual la energía del tiempo sin servicio.
            self._close_hour(datetime.fromisoformat(saved_hour), {**self.acc, **data.get("acc", {})})
            self.hour = hour_start(now)

    def snapshot(self) -> dict:
        return {
            "records": [r.to_dict() for r in self.records],
            "hour": self.hour.isoformat() if self.hour else None,
            "acc": self.acc,
            "prev": {"hour": self.prev["hour"].isoformat(), "acc": self.prev["acc"]} if self.prev else None,
            "counters": {k: c.last for k, c in self.counters.items()},
            "ev_total": self.ev_total,
            "enabled": self.enabled,
            "forced": self.forced.to_dict() if self.forced else None,
            "forced_inputs": self.forced_inputs,
            "soc": self.soc.to_dict(),
            "events": list(self.events),
            "trace": list(self.trace),
        }

    # ------------------------------------------------------------------ utilidades
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def event(self, text: str, level: str = "info") -> None:
        stamp = self.now()
        self.events.appendleft({"time": stamp.strftime("%d/%m %H:%M"), "level": level, "text": text})
        _LOGGER.log(logging.getLevelName(level.upper()), text)

    def _price(self, when: datetime) -> float:
        price = self.tariff.price_at(when, self.workday_override)
        return price if price is not None else 0.0

    def _record(self, hour: datetime, acc: dict) -> HourRecord:
        return HourRecord(hour.isoformat(), acc["gen"], acc["home"], acc["ev"],
                          self._price(hour), self.cfg.compensation_price)

    def current_record(self) -> HourRecord:
        return self._record(self.hour or hour_start(self.now()), self.acc)

    def _close_hour(self, hour: datetime, acc: dict) -> None:
        record = self._record(hour, acc)
        self.records.append(record)
        limit = self.now() - timedelta(days=KEEP_DAYS)
        self.records = [r for r in self.records if r.start >= limit]
        if self.pub:
            self.pub.publish_state("hour_balance_closed", round(record.balance * 1000), {
                "hora": record.start.strftime("%d/%m %H:00"), "generacion_kwh": round(record.gen, 3),
                "hogar_kwh": round(record.home, 3), "cargador_kwh": round(record.ev, 3),
                "importado_kwh": round(record.grid_import, 3), "coche_solar_kwh": round(record.ev_solar, 3),
            })

    # ------------------------------------------------------------------ comandos MQTT
    def handle_command(self, key: str, payload: str) -> None:
        now = self.now()
        if key == "enabled":
            self.enabled = payload.upper() == "ON"
            if not self.enabled:
                self.charger.release()
            self.event("Control automático " + ("activado" if self.enabled else "desactivado"))
            self.last_decision_at = None
        elif key == "forced_start":
            self.forced_inputs["start"] = payload.strip()
        elif key in ("forced_hours", "forced_current"):
            try:
                value = float(payload)
            except ValueError:
                _LOGGER.warning("Valor no válido para %s: %r", key, payload)
                return
            if key == "forced_hours":
                self.forced_inputs["hours"] = value
            else:
                self.forced_inputs["current"] = max(self.cfg.min_current, min(self.cfg.max_current, int(value)))
        elif key == "forced_schedule":
            try:
                start = parse_start(self.forced_inputs["start"], now)
                self.forced = ForcedCharge.create(start, float(self.forced_inputs["hours"]),
                                                  int(self.forced_inputs["current"]), now)
                self.forced_message = f"Programada: {self.forced.describe()}"
                self.event(f"Carga forzada programada {self.forced.describe()}")
            except (ScheduleError, ValueError) as err:
                self.forced_message = f"Error: {err}"
                self.event(f"No se pudo programar la carga forzada: {err}", "warning")
        elif key == "forced_cancel":
            if self.forced:
                self.event("Carga forzada cancelada")
            self.forced = None
            self.forced_message = "Sin carga programada"
            self.last_decision_at = None
        self.wake.set()

    # ------------------------------------------------------------------ ciclo
    async def _read(self, entity_id: str) -> dict | None:
        if not entity_id:
            return None
        try:
            return await self.ha.get_state(entity_id)
        except HAError as err:
            _LOGGER.debug("Lectura fallida %s: %s", entity_id, err)
            return None

    async def poll(self) -> None:
        now = self.now()
        if self.hour is None:
            self.hour = hour_start(now)
        if hour_start(now) != self.hour:
            if self.prev:
                self._close_hour(self.prev["hour"], self.prev["acc"])
            self.prev = {"hour": self.hour, "acc": self.acc}
            self.hour = hour_start(now)
            self.acc = {"gen": 0.0, "home": 0.0, "ev": 0.0}
            self.last_decision_at = None

        c = self.cfg
        ids = [c.generation_power_entity, c.home_power_entity, c.charger_power_entity,
               c.generation_energy_entity, c.home_energy_entity, c.charger_energy_entity,
               c.charger_start_entity, c.charger_current_entity, c.charger_current_readback_entity,
               c.charger_state_entity, c.car_soc_entity, c.workday_entity]
        (p_gen, p_home, p_ev, e_gen, e_home, e_ev, ch_start, ch_cur, ch_readback, ch_state, soc,
         workday) = await asyncio.gather(*(self._read(i) for i in ids))

        self.powers = {"gen": to_float(p_gen), "home": to_float(p_home), "ev": to_float(p_ev)}
        if c.home_includes_charger and self.powers["home"] is not None:
            self.powers["home"] = max(0.0, self.powers["home"] - (self.powers["ev"] or 0.0))
        self.workday_override = (workday["state"] == "on") if is_available(workday) else None
        deltas = {k: self.counters[k].update(to_float(st)) for k, st in (("gen", e_gen), ("home", e_home), ("ev", e_ev))}
        ev_window = None
        if c.charger_energy_source == "potencia":
            integrated, ev_window = self._integrate_ev_power(now)
            if ev_window is not None:
                deltas["ev"] = integrated
            # Si falta la potencia (corte o reinicio), ese tramo se cubre con el contador de energía.
        if c.home_includes_charger:
            deltas["home"] = max(0.0, deltas["home"] - deltas["ev"])
        for key, state in (("gen", e_gen), ("home", e_home), ("ev", e_ev)):
            if key == "ev" and ev_window:
                self._allocate(key, deltas[key], *ev_window)
                continue
            stamp = _stamp(state) or now
            self._allocate(key, deltas[key], self.stamps[key], stamp)
            if is_available(state):
                self.stamps[key] = stamp
        self.ev_total += deltas["ev"]
        self._stamps_raw = {"gen_kw": _raw_stamp(p_gen), "home_kw": _raw_stamp(p_home),
                            "gen_kwh": _raw_stamp(e_gen), "home_kwh": _raw_stamp(e_home), "ev_kwh": _raw_stamp(e_ev)}
        if self.prev and now >= self.hour + timedelta(minutes=self.cfg.hour_close_delay_minutes):
            self._close_hour(self.prev["hour"], self.prev["acc"])
            self.prev = None

        if is_available(soc):
            stamp = soc.get("last_updated") or soc.get("last_changed")
            if self.soc.update_real(to_float(soc, unit_aware=False), stamp, self.ev_total):
                self.event(f"Batería del coche (dato real): {to_float(soc, unit_aware=False):.0f} %")

        changes = self.charger.read(ChargerReadings(ch_start, ch_cur, ch_readback, ch_state), now)
        for change in changes:
            if change == "plugged":
                self.event("Coche conectado")
                self.last_decision_at = None
            elif change == "unplugged":
                self.event("Coche desconectado")
        await self._track_connectivity(next((c for c in changes if c in ("online", "offline")), None), now)
        await self._control(now)

        sent = await self.charger.reconcile(now)
        if sent or self._decided:
            self._trace(now, sent)
        self._decided = False
        if sent:
            if self.charger.start_blocked:
                self.event("El coche no inicia la carga tras varios intentos (¿batería llena?); "
                           "se reintentará cuando cambie el estado del cargador", "warning")
            else:
                _LOGGER.info("Orden enviada al cargador: %s", sent)
        self.publish(now)

    def _integrate_ev_power(self, now: datetime) -> tuple[float, tuple[datetime, datetime] | None]:
        """Energía del cargador desde la lectura anterior, por el método del trapecio sobre su potencia."""
        kw = self.powers["ev"]
        prev, self._ev_power_prev = self._ev_power_prev, ((now, kw) if kw is not None else None)
        if prev is None or kw is None:
            return 0.0, None
        t0, kw0 = prev
        hours = (now - t0).total_seconds() / 3600
        # Un hueco largo (addon parado o sensor sin datos) no se rellena con una suposición.
        if hours <= 0 or hours > 3 * self.cfg.poll_interval_seconds / 3600 + 1 / 60:
            return 0.0, None
        return max(0.0, (kw0 + kw) / 2 * hours), (t0, now)

    def _trace(self, now: datetime, sent: str | None) -> None:
        d, ch = self.decision, self.charger
        r = lambda v, n=3: None if v is None else round(v, n)  # noqa: E731
        self.trace.append({
            "t": now.isoformat(timespec="seconds"), "modo": self.mode,
            "hora_kwh": {k: r(v) for k, v in self.acc.items()},
            "potencia_kw": {k: r(v) for k, v in self.powers.items()},
            "decision": None if d is None else {
                "cargar": d.charge, "A": d.current_a, "motivo": d.reason, "saldo_wh": round(d.balance_wh),
                "disponible_wh": round(d.available_wh), "prevision_wh": round(d.forecast_wh),
                "min_restantes": round(d.minutes_left, 1)},
            "cargador": {"online": ch.online, "estado": ch.state_text, "cargando": ch.actual_on,
                         "A_real": ch.actual_current, "deseado": ch.desired_on, "A_deseado": ch.desired_current},
            "orden": sent, "lecturas": self._stamps_raw,
        })

    def diagnostics(self) -> dict:
        now = self.now()
        recent = [r.to_dict() for r in self.records if r.start >= now - timedelta(days=14)]
        cfg = {k: (list(v) if isinstance(v, (tuple, frozenset)) else v)
               for k, v in self.cfg.__dict__.items() if k != "tariff_periods"}
        cfg["holidays"] = sorted(str(d) for d in self.cfg.holidays)
        return {"generado": now.isoformat(timespec="seconds"), "version": VERSION, "configuracion": cfg,
                "modo": self.mode, "hora_en_curso": {"inicio": self.hour.isoformat() if self.hour else None,
                                                      **self.acc},
                "horas_cerradas": recent, "eventos": list(self.events), "traza": list(self.trace)}

    def _allocate(self, key: str, delta: float, t0: datetime | None, t1: datetime) -> None:
        """Reparte un incremento entre la hora anterior (si sigue abierta) y la actual,
        en proporción al tiempo que cubre la lectura a cada lado del cambio de hora."""
        if delta <= 0:
            return
        if self.prev is None:
            self.acc[key] += delta
            return
        boundary = self.hour
        if t0 is None or t1 <= t0:
            frac_prev = 1.0 if t1 < boundary else 0.0
        else:
            frac_prev = min(1.0, max(0.0, (boundary - t0) / (t1 - t0)))
        self.prev["acc"][key] += delta * frac_prev
        self.acc[key] += delta * (1.0 - frac_prev)

    async def _track_connectivity(self, change: str | None, now: datetime) -> None:
        c = self.cfg
        if change == "online":
            if self.offline_logged:
                self.event("Cargador reconectado; se reaplica el estado deseado")
                if self.notified_offline:
                    try:
                        await self.ha.dismiss(NOTIFICATION_ID)
                    except HAError:
                        pass
            else:
                self.event("Microcorte del cargador dentro de la tolerancia", "debug")
            self.offline_logged = self.notified_offline = False
            return
        if self.charger.online or self.charger.offline_since is None:
            return
        offline_s = (now - self.charger.offline_since).total_seconds()
        if offline_s >= c.disconnect_tolerance_seconds and not self.offline_logged:
            self.event(f"Cargador sin conexión desde las {self.charger.offline_since:%H:%M}", "warning")
            self.offline_logged = True
        if offline_s >= c.disconnect_notify_minutes * 60 and not self.notified_offline:
            try:
                await self.ha.notify("Solar Charger", "El cargador no responde desde las "
                                     f"{self.charger.offline_since:%H:%M}. Revisa su conexión WiFi.", NOTIFICATION_ID)
                self.notified_offline = True
            except HAError as err:
                _LOGGER.warning("No se pudo crear la notificación: %s", err)

    async def _control(self, now: datetime) -> None:
        # Carga forzada: termina siempre a la hora fijada, aunque haya habido cortes.
        if self.forced and self.forced.is_finished(now):
            self.event(f"Carga forzada finalizada ({self.forced.describe()})")
            self.forced = None
            self.forced_message = "Sin carga programada"
            self.last_decision_at = None
        if self.forced and self.forced.is_active(now):
            self.mode = "Carga forzada"
            self.charger.set_desired(True, self.forced.current_a)
            self.forced_message = f"En curso hasta {self.forced.end:%H:%M} · {self.forced.current_a} A"
            return
        if not self.enabled:
            self.mode = "Manual (control desactivado)"
            self.charger.release()
            return
        if not self.charger.car_connected:
            self.mode = "Coche desconectado"
            self.charger.set_desired(False, self.charger.desired_current or self.cfg.min_current)
            self.decision = None
            return

        due = (self.last_decision_at is None or
               now - self.last_decision_at >= timedelta(minutes=self.cfg.decision_interval_minutes))
        if not due:
            return
        charging = bool(self.charger.desired_on)
        current = self.charger.desired_current or self.cfg.min_current
        d = decide(ControlInputs(now, self.acc["gen"], self.acc["home"], self.acc["ev"],
                                 self.powers["gen"], self.powers["home"], charging, current, self.last_switch),
                   self.params)
        self.decision, self.last_decision_at = d, now
        self._decided = True
        if d.charge != charging or self.charger.desired_on is None:
            self.last_switch = now
            self.event(("Arranque a %d A" % d.current_a if d.charge else "Pausa") + f" · {d.reason}")
        elif d.charge and d.current_a != current:
            self.event(f"Ajuste {current} → {d.current_a} A · {d.reason}")
        self.charger.set_desired(d.charge, d.current_a)
        self.mode = "Solar · cargando" if d.charge else "Solar · en pausa"

    # ------------------------------------------------------------------ publicación
    def publish(self, now: datetime) -> None:
        if not self.pub:
            return
        p = self.pub.publish_state
        current = self.current_record()
        closed = self.records + ([self._record(self.prev["hour"], self.prev["acc"])] if self.prev else [])
        stats = compute_stats(closed, current, now, self.cfg.coverage_target_percent)
        d = self.decision
        r1 = lambda v, n=1: None if v is None else round(v, n)  # noqa: E731
        mode = self.mode if self.charger.online else f"{self.mode} · cargador sin conexión"
        p("mode", mode, {"motivo": d.reason if d else None, "disponible_wh": round(d.available_wh) if d else None,
                         "ultima_decision": self.last_decision_at.isoformat() if self.last_decision_at else None})
        pw = self.powers
        p("power_generation", r1(pw["gen"], 3))
        p("power_home", r1(pw["home"], 3))
        p("power_charger", r1(pw["ev"], 3))
        grid = None if None in pw.values() else pw["home"] + pw["ev"] - pw["gen"]
        p("power_grid", r1(grid, 3))
        p("target_current", self.charger.desired_current if self.charger.desired_on else 0)
        p("hour_balance", round(current.balance * 1000))
        p("hour_forecast", round(d.forecast_wh) if d else None)
        p("hour_minutes_left", round(minutes_left_in_hour(now)))
        p("hour_generation", round(current.gen, 3))
        p("hour_home", round(current.home, 3))
        p("hour_charger", round(current.ev, 3))
        p("coverage_today", r1(stats.coverage_today))
        p("coverage_month", r1(stats.coverage_month))
        p("coverage_year", r1(stats.coverage_year))
        p("coverage_year_projection", r1(stats.coverage_year_projection))
        p("self_consumed_year", round(stats.self_consumed_year, 2))
        p("consumption_year", round(stats.consumption_year, 2))
        p("kwh_to_target", round(stats.kwh_to_target, 1))
        p("ev_today", round(stats.ev_today, 3))
        p("ev_solar_share_today", r1(stats.ev_solar_share_today))
        p("ev_month", round(stats.ev_month, 2))
        p("ev_solar_share_month", r1(stats.ev_solar_share_month))
        p("soc_estimated", r1(self.soc.estimate(self.ev_total)),
          {"ultimo_dato_real": self.soc.anchor_soc, "fecha_dato_real": self.soc.anchor_stamp})
        p("savings_today", round(stats.savings_today, 2))
        p("savings_month", round(stats.savings_month, 2))
        p("savings_year", round(stats.savings_year, 2))
        p("current_price", self._price(now))
        p("forced_status", self.forced_message[:250])
        visible = [e for e in self.events if e["level"] != "debug"] or [{"time": "", "text": "Sin eventos"}]
        p("last_event", f"{visible[0]['time']} {visible[0]['text']}".strip()[:250], {"eventos": list(self.events)[:20]})
        p("charger_online", self.charger.online)
        p("enabled", self.enabled)
        p("forced_start", self.forced_inputs["start"])
        p("forced_hours", float(self.forced_inputs["hours"]))
        p("forced_current", int(self.forced_inputs["current"]))

    async def run(self, stop: asyncio.Event) -> None:
        save_every = max(1, 300 // self.cfg.poll_interval_seconds)
        tick = 0
        while not stop.is_set():
            commanded = self.wake.is_set()
            self.wake.clear()
            try:
                await self.poll()
            except Exception:  # noqa: BLE001 - el addon no debe detenerse por un ciclo fallido
                _LOGGER.exception("Error en el ciclo de control")
            tick += 1
            if commanded or tick % save_every == 0:
                try:
                    save_state(self.snapshot())
                except OSError as err:
                    _LOGGER.error("No se pudo guardar el estado: %s", err)
            # Espera al siguiente ciclo, o despierta antes si llega una orden desde HA.
            waiter = asyncio.ensure_future(self.wake.wait())
            stopper = asyncio.ensure_future(stop.wait())
            await asyncio.wait({waiter, stopper}, timeout=self.cfg.poll_interval_seconds,
                               return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            stopper.cancel()
        save_state(self.snapshot())
