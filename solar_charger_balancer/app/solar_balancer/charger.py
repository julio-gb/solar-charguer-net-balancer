"""Control del cargador con reconciliación de estado y tolerancia a microcortes.

El addon guarda el estado DESEADO (cargando o no, amperios). En cada ciclo de lectura
lo compara con el estado REAL y, si el cargador está en línea y no coincide, reenvía
la orden con espera progresiva. Tras un corte, el estado se reaplica al reconectar.

Admite dos formas de control:
- Botones de iniciar/parar (p. ej. Beny WiFi) o un interruptor (switch/input_boolean).
- Intensidad en una entidad number, opcionalmente confirmada con un botón «enviar»
  y leída de vuelta en un sensor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ha_client import HAClient, HAError, is_available, to_float

_LOGGER = logging.getLogger(__name__)
MAX_BACKOFF_S = 300
MAX_START_ATTEMPTS = 3


@dataclass(frozen=True)
class ChargerEntities:
    start: str
    current: str
    stop: str = ""
    current_apply: str = ""
    current_readback: str = ""
    state: str = ""
    charging_states: tuple[str, ...] = ("charging",)
    unplugged_states: tuple[str, ...] = ("unplugged",)

    @property
    def is_switch(self) -> bool:
        return self.start.split(".", 1)[0] in ("switch", "input_boolean")


@dataclass
class ChargerReadings:
    start: dict | None = None
    current: dict | None = None
    readback: dict | None = None
    state: dict | None = None
    extra: dict = field(default_factory=dict)


class Charger:
    def __init__(self, ha: HAClient, entities: ChargerEntities):
        self._ha = ha
        self.e = entities
        self.desired_on: bool | None = None
        self.desired_current: int | None = None
        self.actual_on: bool | None = None
        self.actual_current: float | None = None
        self.number_value: float | None = None
        self.state_text: str | None = None
        self.car_connected = True
        self.online = True
        self.offline_since: datetime | None = None
        self.start_blocked = False
        self._commanded_on: bool | None = None
        self._start_attempts = 0
        self._failures = 0
        self._next_attempt: datetime | None = None

    # ------------------------------------------------------------------ lectura
    def read(self, r: ChargerReadings, now: datetime) -> list[str]:
        """Actualiza el estado real. Devuelve eventos: 'offline', 'online', 'plugged', 'unplugged'."""
        events = []
        key_states = [r.current] + ([r.state] if self.e.state else []) + ([r.start] if self.e.is_switch else [])
        available = all(is_available(s) for s in key_states)
        if available:
            if not self.online:
                events.append("online")
            self.online, self.offline_since = True, None
        else:
            if self.online:
                events.append("offline")
                self.offline_since = now
            self.online = False
            return events

        self.number_value = to_float(r.current, unit_aware=False)
        readback = to_float(r.readback, unit_aware=False) if self.e.current_readback else None
        self.actual_current = readback if readback is not None else self.number_value

        if self.e.state:
            text = str(r.state["state"]).lower()
            if text != self.state_text:
                self._start_attempts, self.start_blocked = 0, False
            self.state_text = text
            self.actual_on = text in self.e.charging_states
            connected = text not in self.e.unplugged_states
            if connected != self.car_connected:
                events.append("plugged" if connected else "unplugged")
            self.car_connected = connected
        elif self.e.is_switch:
            self.actual_on = r.start["state"] == "on"
        if self.actual_on:
            self._start_attempts, self.start_blocked = 0, False
        return events

    # ------------------------------------------------------------------ deseado
    def set_desired(self, on: bool, current: int) -> None:
        if (on, current) != (self.desired_on, self.desired_current):
            self._failures, self._next_attempt = 0, None
        if not on:
            self._start_attempts, self.start_blocked = 0, False
        self.desired_on, self.desired_current = on, current

    def release(self) -> None:
        """Deja de controlar el cargador (control automático desactivado)."""
        self.desired_on = None

    def _current_ok(self) -> bool:
        return self.actual_current is None or self.desired_current is None or round(self.actual_current) == self.desired_current

    def _onoff_ok(self) -> bool:
        if self.actual_on is None:  # sin forma de leer el estado: se confía en la última orden enviada
            return self._commanded_on == self.desired_on
        if self.desired_on and (not self.car_connected or self.start_blocked):
            return True
        return self.actual_on == self.desired_on

    def in_sync(self) -> bool:
        return self.desired_on is None or (self._current_ok() and self._onoff_ok())

    # ------------------------------------------------------------------ órdenes
    async def _press(self, entity_id: str) -> None:
        await self._ha.call_service("button", "press", {"entity_id": entity_id})

    async def _send_current(self) -> None:
        if self.number_value is None or round(self.number_value) != self.desired_current:
            domain = self.e.current.split(".", 1)[0]
            await self._ha.call_service(domain, "set_value", {"entity_id": self.e.current, "value": self.desired_current})
        if self.e.current_apply:
            await self._press(self.e.current_apply)

    async def _start(self) -> None:
        if self.e.is_switch:
            await self._ha.call_service(self.e.start.split(".", 1)[0], "turn_on", {"entity_id": self.e.start})
        else:
            await self._press(self.e.start)

    async def _stop(self) -> None:
        if self.e.is_switch:
            await self._ha.call_service(self.e.start.split(".", 1)[0], "turn_off", {"entity_id": self.e.start})
        elif self.e.stop:
            await self._press(self.e.stop)

    async def reconcile(self, now: datetime) -> str | None:
        """Envía órdenes si hace falta. Devuelve una descripción de lo enviado o None."""
        if self.in_sync():
            self._failures, self._next_attempt = 0, None
            return None
        if not self.online or (self._next_attempt and now < self._next_attempt):
            return None
        sent = []
        try:
            if not self._current_ok():
                await self._send_current()
                sent.append(f"{self.desired_current} A")
            if not self._onoff_ok():
                if self.desired_on:
                    if self._start_attempts >= MAX_START_ATTEMPTS:
                        self.start_blocked = True
                        return "sin respuesta del coche: se deja de insistir"
                    await self._start()
                    self._commanded_on = True
                    self._start_attempts += 1
                    sent.append("iniciar carga")
                else:
                    await self._stop()
                    self._commanded_on = False
                    sent.append("parar carga")
            # Si el cargador no refleja la orden, cada reenvío espera el doble (20 s, 40 s… máx. 5 min).
            self._next_attempt = now + timedelta(seconds=self._backoff())
            self._failures += 1
            return ", ".join(sent) or None
        except HAError as err:
            self._failures += 1
            wait = self._backoff()
            self._next_attempt = now + timedelta(seconds=wait)
            _LOGGER.warning("Orden al cargador fallida (%s); reintento en %s s", err, wait)
            return None

    def _backoff(self) -> int:
        return min(MAX_BACKOFF_S, 20 * 2 ** self._failures)
