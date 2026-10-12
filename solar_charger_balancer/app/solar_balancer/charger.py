"""Control del cargador con reconciliación de estado y tolerancia a microcortes.

El addon guarda el estado DESEADO (encendido/apagado, amperios). En cada ciclo de
lectura compara con el estado REAL y, si el cargador está en línea y no coincide,
reenvía la orden con espera progresiva entre reintentos. Así, tras un corte, el
estado se reaplica automáticamente al reconectar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .ha_client import HAClient, HAError, is_available, to_float

_LOGGER = logging.getLogger(__name__)
MAX_BACKOFF_S = 300


class Charger:
    def __init__(self, ha: HAClient, switch_entity: str, current_entity: str):
        self._ha = ha
        self.switch_entity = switch_entity
        self.current_entity = current_entity
        self.desired_on: bool | None = None
        self.desired_current: int | None = None
        self.actual_on: bool | None = None
        self.actual_current: float | None = None
        self.online = True
        self.offline_since: datetime | None = None
        self._failures = 0
        self._next_attempt: datetime | None = None

    def read(self, switch_state: dict | None, current_state: dict | None, now: datetime) -> str | None:
        """Actualiza el estado real. Devuelve 'offline'/'online' si cambia la conectividad."""
        available = is_available(switch_state) and is_available(current_state)
        change = None
        if available:
            self.actual_on = switch_state["state"] == "on"
            self.actual_current = to_float(current_state, unit_aware=False)
            if not self.online:
                change = "online"
            self.online, self.offline_since = True, None
        else:
            if self.online:
                change = "offline"
                self.offline_since = now
            self.online = False
        return change

    def set_desired(self, on: bool, current: int) -> None:
        if (on, current) != (self.desired_on, self.desired_current):
            self._failures, self._next_attempt = 0, None
        self.desired_on, self.desired_current = on, current

    def in_sync(self) -> bool:
        if self.desired_on is None:
            return True
        if self.actual_on != self.desired_on:
            return False
        return not self.desired_on or self.actual_current is None or round(self.actual_current) == self.desired_current

    async def reconcile(self, now: datetime) -> str | None:
        """Envía órdenes si hace falta. Devuelve una descripción de lo enviado o None."""
        if self.in_sync():
            self._failures, self._next_attempt = 0, None
            return None
        if not self.online:
            return None
        if self._next_attempt and now < self._next_attempt:
            return None
        try:
            sent = []
            if self.desired_current is not None and (self.actual_current is None or round(self.actual_current) != self.desired_current):
                domain = self.current_entity.split(".", 1)[0]
                await self._ha.call_service(domain, "set_value", {"entity_id": self.current_entity, "value": self.desired_current})
                sent.append(f"{self.desired_current} A")
            if self.actual_on != self.desired_on:
                domain = self.switch_entity.split(".", 1)[0]
                await self._ha.call_service(domain, "turn_on" if self.desired_on else "turn_off", {"entity_id": self.switch_entity})
                sent.append("encender" if self.desired_on else "apagar")
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
