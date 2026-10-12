"""Prueba de humo: cliente HTTP real contra un HA simulado y publicación MQTT sin broker."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web

from solar_balancer.ha_client import HAClient
from solar_balancer.mqtt_bridge import MqttBridge
from solar_balancer.service import Balancer

from helpers import make_config

STATES = {
    "sensor.pv_power": ("1.2", "kW"), "sensor.home_power": ("250", "W"), "sensor.ev_power": ("0", "kW"),
    "sensor.pv_energy": ("100.0", "kWh"), "sensor.home_energy": ("50000", "Wh"), "sensor.ev_energy": ("20", "kWh"),
    "switch.ev_charger": ("off", None), "number.ev_current": ("6", "A"),
}


async def _scenario():
    calls = []

    async def state(request):
        entity = request.match_info["entity"]
        if entity not in STATES:
            return web.Response(status=404)
        value, unit = STATES[entity]
        return web.json_response({"entity_id": entity, "state": value,
                                  "attributes": {"unit_of_measurement": unit} if unit else {},
                                  "last_updated": "2026-10-10T13:00:00+00:00"})

    async def service(request):
        calls.append((request.match_info["domain"], request.match_info["service"], await request.json()))
        return web.json_response([])

    app = web.Application()
    app.router.add_get("/api/states/{entity}", state)
    app.router.add_post("/api/services/{domain}/{service}", service)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    published = {}
    async with aiohttp.ClientSession() as session:
        ha = HAClient(session, f"http://127.0.0.1:{port}/api", "token")
        balancer = Balancer(make_config(), ha, ZoneInfo("Europe/Madrid"))
        # Hora fija al inicio de una hora: el resultado no depende del reloj real.
        balancer.now = lambda: datetime(2026, 10, 10, 13, 0, 30, tzinfo=ZoneInfo("Europe/Madrid"))
        bridge = MqttBridge(asyncio.get_running_loop(), balancer.handle_command)
        bridge._client.publish = lambda topic, payload, retain=False: published.__setitem__(topic, payload)
        balancer.pub = bridge
        await balancer.poll()
        await balancer.poll()
    await runner.cleanup()
    return calls, published, balancer


def test_smoke_poll_and_publish():
    calls, published, balancer = asyncio.run(_scenario())
    assert balancer.powers["home"] == 0.25                        # W convertidos a kW
    assert published["solar_charger_balancer/power_grid/state"] == "-0.95"
    assert published["solar_charger_balancer/mode/state"].startswith("Solar")
    assert any(c[1] == "turn_on" for c in calls)                   # 0,95 kW de excedente → carga
