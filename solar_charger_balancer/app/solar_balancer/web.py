"""Página de configuración del addon, servida por Ingress (panel lateral de HA)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from aiohttp import web

from .config import ConfigError
from .ha_client import HAClient, HAError
from .settings import SECTIONS, check, load_raw, save_raw, validate

_LOGGER = logging.getLogger(__name__)
INDEX = Path(__file__).with_name("web") / "index.html"
INGRESS_IP = "172.30.32.2"
ENTITY_DOMAINS = {"sensor", "binary_sensor", "switch", "input_boolean", "number", "input_number", "button"}


def _entity_summary(state: dict) -> dict:
    attrs = state.get("attributes", {})
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name") or state["entity_id"],
        "state": state.get("state"),
        "unit": attrs.get("unit_of_measurement") or "",
        "device_class": attrs.get("device_class") or "",
    }


def create_app(ha: HAClient, on_saved: Callable[[], Awaitable[None] | None], status: Callable[[], dict],
               allowed_ips: set[str] | None = None,
               diagnostics: Callable[[], dict] | None = None) -> web.Application:
    allowed = allowed_ips if allowed_ips is not None else {INGRESS_IP}

    @web.middleware
    async def only_ingress(request, handler):
        if allowed and request.remote not in allowed:
            return web.Response(status=403, text="Acceso solo a través de Home Assistant")
        return await handler(request)

    async def index(request):
        return web.Response(text=INDEX.read_text(encoding="utf-8"), content_type="text/html")

    async def get_schema(request):
        return web.json_response({"sections": SECTIONS})

    async def get_settings(request):
        return web.json_response({"values": load_raw(), "status": status()})

    async def get_entities(request):
        try:
            states = await ha.get_states()
        except HAError as err:
            return web.json_response({"error": f"No se pudieron leer las entidades: {err}"}, status=502)
        items = [_entity_summary(s) for s in states if s.get("entity_id", "").split(".")[0] in ENTITY_DOMAINS]
        items.sort(key=lambda e: e["name"].lower())
        return web.json_response({"entities": items})

    async def post_settings(request):
        try:
            raw = await request.json()
        except ValueError:
            return web.json_response({"error": "Datos no válidos"}, status=400)
        merged = {**load_raw(), **raw}
        clean, errors = check(merged)
        if errors:
            return web.json_response({"errors": errors}, status=400)
        try:
            validate(clean)
        except (ConfigError, ValueError, KeyError) as err:
            return web.json_response({"error": str(err)}, status=400)
        save_raw(clean)
        result = on_saved()
        if result is not None:
            await result
        _LOGGER.info("Configuración guardada desde la página del addon")
        return web.json_response({"ok": True})

    async def get_diagnostics(request):
        data = diagnostics() if diagnostics else {}
        name = f"solar-charger-diagnostico-{data.get('generado', '')[:16].replace(':', '')}.json"
        return web.json_response(data, dumps=lambda o: json.dumps(o, ensure_ascii=False, indent=1, default=str),
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    app = web.Application(middlewares=[only_ingress])
    app.router.add_get("/", index)
    app.router.add_get("/api/schema", get_schema)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_get("/api/entities", get_entities)
    app.router.add_post("/api/settings", post_settings)
    app.router.add_get("/api/diagnostics", get_diagnostics)
    return app
