import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from solar_balancer.charger import Charger, ChargerEntities, ChargerReadings
from solar_balancer.service import Balancer

from helpers import make_config

TZ = ZoneInfo("Europe/Madrid")


class FakeHA:
    def __init__(self):
        self.states = {}
        self.calls = []

    def set(self, entity, state, unit=None, stamp="2026-10-10T13:00:00+02:00"):
        attrs = {"unit_of_measurement": unit} if unit else {}
        self.states[entity] = {"state": str(state), "attributes": attrs, "last_updated": stamp}

    async def get_state(self, entity_id):
        return self.states.get(entity_id)

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        entity = data["entity_id"]
        if service == "set_value":
            self.states[entity]["state"] = str(data["value"])
        elif service in ("turn_on", "turn_off"):
            self.states[entity]["state"] = "on" if service == "turn_on" else "off"

    async def notify(self, *args):
        self.calls.append(("notify",))

    async def dismiss(self, *args):
        self.calls.append(("dismiss",))


def run(coro):
    return asyncio.run(coro)


def _readings(ha, *ids):
    return ChargerReadings(*(ha.states.get(i) if i else None for i in ids))


def test_charger_reapplies_after_reconnect():
    ha = FakeHA()
    ha.set("switch.ev", "off")
    ha.set("number.ev", 6)
    ch = Charger(ha, ChargerEntities(start="switch.ev", current="number.ev"))
    now = datetime(2026, 10, 10, 13, 0, tzinfo=TZ)
    ch.set_desired(True, 8)
    assert ch.read(ChargerReadings(), now) == ["offline"]
    assert run(ch.reconcile(now)) is None and ha.calls == []
    assert ch.read(_readings(ha, "switch.ev", "number.ev"), now + timedelta(seconds=40)) == ["online"]
    assert run(ch.reconcile(now + timedelta(seconds=40))) == "8 A, iniciar carga"
    ch.read(_readings(ha, "switch.ev", "number.ev"), now)
    assert ch.in_sync()


BENY = ChargerEntities(start="button.b_start", stop="button.b_stop", current="number.b_cur",
                       current_apply="button.b_send", current_readback="sensor.b_cur", state="sensor.b_state")


class BenyHA(FakeHA):
    """Simula la integración Beny: botones, número + botón enviar, sensor de estado."""

    def __init__(self, state="standby", accepts=True):
        super().__init__()
        self.accepts = accepts
        self.set("number.b_cur", 6)
        self.set("sensor.b_cur", 6, "A")
        self.set("sensor.b_state", state)

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data["entity_id"]))
        e = data["entity_id"]
        if service == "set_value":
            self.states[e]["state"] = str(data["value"])
        elif e == "button.b_send":
            self.states["sensor.b_cur"]["state"] = self.states["number.b_cur"]["state"]
        elif e == "button.b_start" and self.accepts:
            self.states["sensor.b_state"]["state"] = "charging"
        elif e == "button.b_stop":
            self.states["sensor.b_state"]["state"] = "standby"


def beny_read(ha, ch, now):
    return ch.read(_readings(ha, None, "number.b_cur", "sensor.b_cur", "sensor.b_state"), now)


def test_beny_start_current_and_stop():
    ha = BenyHA()
    ch = Charger(ha, BENY)
    now = datetime(2026, 10, 10, 13, 0, tzinfo=TZ)
    beny_read(ha, ch, now)
    ch.set_desired(True, 10)
    assert run(ch.reconcile(now)) == "10 A, iniciar carga"
    assert ha.calls == [("number", "set_value", "number.b_cur"), ("button", "press", "button.b_send"),
                        ("button", "press", "button.b_start")]
    beny_read(ha, ch, now)
    assert ch.actual_on and ch.actual_current == 10 and ch.in_sync()
    ch.set_desired(False, 10)
    assert run(ch.reconcile(now)) == "parar carga"
    beny_read(ha, ch, now)
    assert ch.state_text == "standby" and ch.in_sync()


def test_beny_unplugged_sends_nothing_and_full_battery_gives_up():
    ha = BenyHA(state="unplugged")
    ch = Charger(ha, BENY)
    now = datetime(2026, 10, 10, 13, 0, tzinfo=TZ)
    beny_read(ha, ch, now)
    ch.set_desired(True, 6)
    assert run(ch.reconcile(now)) is None and ha.calls == []
    ha.states["sensor.b_state"]["state"] = "standby"
    ha.accepts = False                          # coche lleno: no empieza a cargar
    assert beny_read(ha, ch, now) == ["plugged"]
    for i in range(5):
        now += timedelta(minutes=6)
        run(ch.reconcile(now))
        beny_read(ha, ch, now)
    presses = [c for c in ha.calls if c[2] == "button.b_start"]
    assert len(presses) == 3 and ch.start_blocked and ch.in_sync()


def test_buttons_without_state_sensor_track_last_command():
    ha = BenyHA()
    ch = Charger(ha, ChargerEntities(start="button.b_start", stop="button.b_stop", current="number.b_cur"))
    now = datetime(2026, 10, 10, 13, 0, tzinfo=TZ)
    ch.read(_readings(ha, None, "number.b_cur"), now)
    ch.set_desired(True, 6)
    assert run(ch.reconcile(now)) == "iniciar carga"
    assert ch.in_sync()


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t


def make_balancer():
    ha = FakeHA()
    for e, v, u in [("sensor.pv_power", 1.0, "kW"), ("sensor.home_power", 300, "W"), ("sensor.ev_power", 0, "kW"),
                    ("sensor.pv_energy", 1000.0, "kWh"), ("sensor.home_energy", 500.0, "kWh"),
                    ("sensor.ev_energy", 200.0, "kWh"), ("switch.ev_charger", "off", None), ("number.ev_current", 6, "A")]:
        ha.set(e, v, u)
    b = Balancer(make_config(strategy="prevision", surplus_factor=1.0), ha, TZ)
    b.now = Clock(datetime(2026, 10, 10, 13, 0, 30, tzinfo=TZ))
    return b, ha


def test_poll_starts_charging_with_surplus_and_closes_hour():
    b, ha = make_balancer()
    run(b.poll())
    assert b.mode == "Solar · cargando"
    assert ("switch", "turn_on", {"entity_id": "switch.ev_charger"}) in ha.calls
    # FusionSolar reporta a las 14:03 la energía de 13:58–14:03: 2/5 corresponden a las 13 h.
    ha.set("sensor.pv_energy", 1000.0, "kWh", "2026-10-10T13:58:00+02:00")
    b.now.t = datetime(2026, 10, 10, 13, 59, 0, tzinfo=TZ)
    run(b.poll())
    ha.set("sensor.pv_energy", 1000.1, "kWh", "2026-10-10T14:03:00+02:00")
    b.now.t = datetime(2026, 10, 10, 14, 3, 30, tzinfo=TZ)
    run(b.poll())
    assert b.records == [] and b.prev is not None          # la hora 13 sigue abierta
    b.now.t = datetime(2026, 10, 10, 14, 10, 30, tzinfo=TZ)
    run(b.poll())
    assert len(b.records) == 1
    assert round(b.records[0].gen, 3) == 0.04 and round(b.acc["gen"], 3) == 0.06


def test_forced_charge_commands_and_fixed_end():
    b, ha = make_balancer()
    b.handle_command("forced_start", "2026-10-10 13:00")
    b.handle_command("forced_hours", "1")
    b.handle_command("forced_current", "40")      # se limita a 21 A
    b.handle_command("forced_schedule", "PRESS")
    run(b.poll())
    assert b.mode == "Carga forzada" and b.charger.desired_current == 21
    b.now.t = datetime(2026, 10, 10, 14, 0, 0, tzinfo=TZ)
    run(b.poll())
    assert b.forced is None and b.mode.startswith("Solar")


def test_disabled_control_leaves_charger_alone():
    b, ha = make_balancer()
    b.handle_command("enabled", "OFF")
    run(b.poll())
    assert ha.calls == []


def test_state_roundtrip():
    b, _ = make_balancer()
    run(b.poll())
    b2, _ = make_balancer()
    b2.restore(b.snapshot(), b.now.t)
    assert b2.hour == b.hour and b2.counters["gen"].last == 1000.0


def test_balancer_with_beny_waits_for_car_then_charges():
    ha = BenyHA(state="unplugged")
    for e, v, u in [("sensor.pv_power", 1.5, "kW"), ("sensor.home_power", 0.3, "kW"), ("sensor.ev_power", 0, "kW"),
                    ("sensor.pv_energy", 10.0, "kWh"), ("sensor.home_energy", 5.0, "kWh"), ("sensor.ev_energy", 2.0, "kWh")]:
        ha.set(e, v, u)
    cfg = make_config(charger_start_entity="button.b_start", charger_stop_entity="button.b_stop",
                      charger_current_entity="number.b_cur", charger_current_apply_entity="button.b_send",
                      charger_current_readback_entity="sensor.b_cur", charger_state_entity="sensor.b_state",
                      strategy="prevision", surplus_factor=1.0)
    b = Balancer(cfg, ha, TZ)
    b.now = Clock(datetime(2026, 10, 10, 13, 0, 30, tzinfo=TZ))
    run(b.poll())
    assert b.mode == "Coche desconectado" and ha.calls == []
    ha.states["sensor.b_state"]["state"] = "standby"
    b.now.t += timedelta(seconds=30)
    run(b.poll())
    assert b.mode == "Solar · cargando"
    assert ("button", "press", "button.b_start") in ha.calls
    assert b.events[0]["text"].startswith("Arranque") and b.events[1]["text"] == "Coche conectado"


def test_home_sensor_including_charger_is_corrected_and_traced():
    b, ha = make_balancer()
    b.cfg = make_config(home_includes_charger=True, charger_energy_source="contador")
    ha.set("sensor.home_power", 1700, "W")
    ha.set("sensor.ev_power", 1.4, "kW")
    run(b.poll())
    assert round(b.powers["home"], 2) == 0.3
    ha.set("sensor.home_energy", 501.0, "kWh")      # +1,0 kWh, de ellos 0,7 del cargador
    ha.set("sensor.ev_energy", 200.7, "kWh")
    b.now.t += timedelta(minutes=5)
    run(b.poll())
    assert round(b.acc["home"], 2) == 0.3 and round(b.acc["ev"], 2) == 0.7
    diag = b.diagnostics()
    assert diag["traza"] and diag["traza"][0]["decision"] is not None
    assert diag["configuracion"]["home_includes_charger"] is True



def test_charger_energy_from_power_integration_splits_hours():
    b, ha = make_balancer()
    ha.set("sensor.ev_power", 1.38, "kW")
    b.now.t = datetime(2026, 10, 10, 13, 55, 0, tzinfo=TZ)
    b.hour = datetime(2026, 10, 10, 13, 0, tzinfo=TZ)
    for _ in range(20):                       # 10 min con lecturas cada 30 s (13:55 → 14:05)
        run(b.poll())
        b.now.t += timedelta(seconds=30)
    run(b.poll())
    total = b.prev["acc"]["ev"] + b.acc["ev"]
    assert round(total, 3) == round(1.38 * 10 / 60, 3)
    assert round(b.prev["acc"]["ev"], 3) == round(1.38 * 5 / 60, 3)   # 13:55–14:00 a la hora 13


def test_power_gap_falls_back_to_energy_counter():
    b, ha = make_balancer()
    ha.set("sensor.ev_power", 1.38, "kW")
    run(b.poll())
    ha.set("sensor.ev_power", "unavailable")             # corte: sin potencia
    ha.set("sensor.ev_energy", 200.1, "kWh")
    b.now.t += timedelta(minutes=3)
    run(b.poll())
    assert round(b.acc["ev"], 3) == 0.1                   # se usa el contador para el hueco
    ha.set("sensor.ev_power", 1.38, "kW")
    b.now.t += timedelta(seconds=30)
    run(b.poll())
    b.now.t += timedelta(seconds=30)
    run(b.poll())
    assert abs(b.acc["ev"] - (0.1 + 1.38 * 30 / 3600)) < 1e-6
