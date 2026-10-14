import asyncio
import json

import aiohttp
from aiohttp import web

from solar_balancer import settings
from solar_balancer.web import create_app

from helpers import default_options

ENTITIES = [
    {"entity_id": "sensor.pv_power", "state": "1.2", "attributes": {"unit_of_measurement": "kW", "friendly_name": "FV"}},
    {"entity_id": "sensor.pv_energy", "state": "100", "attributes": {"unit_of_measurement": "kWh"}},
    {"entity_id": "light.salon", "state": "on", "attributes": {}},
]


def test_check_accepts_defaults_and_coerces():
    raw = default_options()
    raw["max_current"] = "21"
    clean, errors = settings.check(raw)
    assert errors == {} and clean["max_current"] == 21


def test_check_reports_field_errors():
    raw = default_options()
    raw["charger_start_entity"] = ""
    raw["min_current"] = 40
    _, errors = settings.check(raw)
    assert set(errors) == {"charger_start_entity", "min_current"}


def test_tariff_gaps_and_overlaps_rejected():
    raw = default_options()
    raw["tariff_periods"] = [p for p in raw["tariff_periods"] if p["start"] != "08:00"]
    _, errors = settings.check(raw)
    assert "falta precio entre 08:00 y 10:00" in errors["tariff_periods"]
    raw = default_options()
    raw["tariff_periods"].append({"days": "festivo", "start": "10:00", "end": "12:00", "price": 0.1})
    _, errors = settings.check(raw)
    assert "solapan" in errors["tariff_periods"]


class FakeHA:
    async def get_states(self):
        return ENTITIES


async def _web_flow(tmp_path, monkeypatch):
    options = tmp_path / "options.json"
    options.write_text(json.dumps(default_options() | {"charger_start_entity": ""}))
    monkeypatch.setattr(settings, "OPTIONS_PATH", options)
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    saved = []
    app = create_app(FakeHA(), lambda: saved.append(True), lambda: {"configured": False}, allowed_ips=set())
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    async with aiohttp.ClientSession() as s:
        assert "Solar Charger" in await (await s.get(base + "/")).text()
        ents = (await (await s.get(base + "/api/entities")).json())["entities"]
        bad = await s.post(base + "/api/settings", json={"min_current": 3, "max_current": 2})
        bad_body = await bad.json()
        ok = await s.post(base + "/api/settings", json={"charger_start_entity": "switch.ev", "compensation_price": 0.03})
        ok_status = ok.status
    await runner.cleanup()
    return ents, bad.status, bad_body, ok_status, saved


def test_web_endpoints(tmp_path, monkeypatch):
    ents, bad_status, bad_body, ok_status, saved = asyncio.run(_web_flow(tmp_path, monkeypatch))
    assert [e["entity_id"] for e in ents] == ["sensor.pv_power", "sensor.pv_energy"]  # sin light.*
    assert bad_status == 400 and "charger_start_entity" in bad_body["errors"]
    assert ok_status == 200 and saved == [True]
    stored = json.loads((tmp_path / "settings.json").read_text())
    assert stored["charger_start_entity"] == "switch.ev" and stored["compensation_price"] == 0.03
    assert settings.load_raw()["compensation_price"] == 0.03


def test_ingress_only(tmp_path):
    async def flow():
        app = create_app(FakeHA(), lambda: None, lambda: {}, allowed_ips={"172.30.32.2"})
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as s:
            status = (await s.get(f"http://127.0.0.1:{port}/api/settings")).status
        await runner.cleanup()
        return status
    assert asyncio.run(flow()) == 403


def test_missing_new_fields_get_defaults():
    raw = default_options()
    for k in ("strategy", "surplus_factor", "home_includes_charger", "charger_charging_states"):
        raw.pop(k, None)
    clean, errors = settings.check(raw)
    assert errors == {} and clean["strategy"] == "acumulado" and clean["charger_charging_states"] == ["charging"]
