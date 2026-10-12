"""Cliente mínimo de la API REST de Home Assistant a través del Supervisor."""
from __future__ import annotations

import logging
import os

import aiohttp

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = {"unavailable", "unknown", "none", ""}
_UNIT_FACTORS = {"w": 0.001, "kw": 1.0, "mw": 1000.0, "wh": 0.001, "kwh": 1.0, "mwh": 1000.0}


class HAError(Exception):
    pass


def to_float(state: dict | None, unit_aware: bool = True) -> float | None:
    """Valor numérico del estado, convertido a kW/kWh si la unidad es W/Wh/MW/MWh."""
    if not state or str(state.get("state", "")).lower() in UNAVAILABLE:
        return None
    try:
        value = float(state["state"])
    except (TypeError, ValueError):
        return None
    if unit_aware:
        unit = str(state.get("attributes", {}).get("unit_of_measurement", "")).lower()
        value *= _UNIT_FACTORS.get(unit, 1.0)
    return value


def is_available(state: dict | None) -> bool:
    return bool(state) and str(state.get("state", "")).lower() not in UNAVAILABLE


class HAClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str | None = None, token: str | None = None):
        self._session = session
        self._base = base_url or "http://supervisor/core/api"
        token = token or os.environ.get("SUPERVISOR_TOKEN", "")
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._timeout = aiohttp.ClientTimeout(total=15)

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with self._session.request(method, f"{self._base}{path}", headers=self._headers,
                                             timeout=self._timeout, **kwargs) as resp:
                if resp.status == 404:
                    return None
                if resp.status >= 400:
                    raise HAError(f"{method} {path}: HTTP {resp.status} {await resp.text()}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HAError(f"{method} {path}: {err}") from err

    async def get_config(self) -> dict:
        return await self._request("GET", "/config") or {}

    async def get_state(self, entity_id: str) -> dict | None:
        if not entity_id:
            return None
        return await self._request("GET", f"/states/{entity_id}")

    async def call_service(self, domain: str, service: str, data: dict) -> None:
        await self._request("POST", f"/services/{domain}/{service}", json=data)

    async def notify(self, title: str, message: str, notification_id: str) -> None:
        await self.call_service("persistent_notification", "create",
                                {"title": title, "message": message, "notification_id": notification_id})

    async def dismiss(self, notification_id: str) -> None:
        await self.call_service("persistent_notification", "dismiss", {"notification_id": notification_id})


async def get_mqtt_service(session: aiohttp.ClientSession) -> dict:
    """Credenciales del broker MQTT (Mosquitto) que publica el Supervisor."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    async with session.get("http://supervisor/services/mqtt",
                           headers={"Authorization": f"Bearer {token}"},
                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status >= 400:
            raise HAError(f"Servicio MQTT no disponible: HTTP {resp.status}")
        return (await resp.json()).get("data", {})
