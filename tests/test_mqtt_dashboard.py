import asyncio
import re

import yaml

from solar_balancer.mqtt_bridge import ENTITIES, MqttBridge, slugify

from helpers import ROOT


def test_slugify_matches_home_assistant_style():
    assert slugify("Solar Charger Cobertura solar año") == "solar_charger_cobertura_solar_ano"
    assert slugify("Solar Charger Previsión cierre hora") == "solar_charger_prevision_cierre_hora"


def test_dashboard_only_uses_addon_entities():
    text = (ROOT / "dashboards" / "solar_charger.yaml").read_text(encoding="utf-8")
    yaml.safe_load(text)
    used = set(re.findall(r"\b(?:sensor|binary_sensor|switch|text|number|button)\.solar_charger_[a-z0-9_]+", text))
    known = {e.entity_id for e in ENTITIES}
    assert used and used <= known, used - known


def test_discovery_payloads():
    loop = asyncio.new_event_loop()
    bridge = MqttBridge(loop, lambda k, v: None, {"forced_current": (6, 21)})
    keys = set()
    for entity in ENTITIES:
        payload = bridge._discovery(entity)
        assert payload["unique_id"] not in keys
        keys.add(payload["unique_id"])
        if entity.component in ("switch", "number", "text", "button"):
            assert "command_topic" in payload
    current = next(e for e in ENTITIES if e.key == "forced_current")
    assert bridge._discovery(current)["max"] == 21
    loop.close()
