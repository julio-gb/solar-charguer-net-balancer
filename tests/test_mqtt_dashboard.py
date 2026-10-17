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


# Claves admitidas por la validación estricta de apexcharts-card 2.2.x (src/types-config.ts).
APEX_CARD_KEYS = {"type", "series", "section_mode", "grid_options", "graph_span", "span", "stacked", "header",
                  "apex_config", "yaxis", "now", "update_interval", "update_delay", "experimental", "show",
                  "all_series_config", "color_list", "chart_type", "locale", "hours_12", "cache", "layout"}
APEX_SERIES_KEYS = {"entity", "attribute", "name", "type", "color", "stack_group", "opacity", "stroke_width",
                    "stroke_dash", "curve", "extend_to", "unit", "float_precision", "fill_raw", "group_by",
                    "invert", "transform", "data_generator", "statistics", "offset", "time_delta", "min", "max",
                    "color_threshold", "yaxis_id", "show", "header_actions"}
APEX_NESTED = {"group_by": {"func", "duration", "fill", "start_with_last"},
               "statistics": {"type", "period", "align"},
               "show": {"legend_value", "in_header", "in_chart", "datalabels", "extremas", "name_in_header",
                        "hidden_by_default", "as_duration", "in_legend", "offset_in_name"},
               "header": {"show", "title", "floating", "show_states", "colorize_states", "standard_format"},
               "yaxis": {"id", "show", "opposite", "min", "max", "decimals", "apex_config", "align_to"},
               "span": {"start", "end", "offset"}}


def _cards(node):
    if isinstance(node, dict):
        if "type" in node:
            yield node
        for v in node.values():
            yield from _cards(v)
    elif isinstance(node, list):
        for v in node:
            yield from _cards(v)


def test_dashboard_apexcharts_options_are_valid():
    dash = yaml.safe_load((ROOT / "dashboards" / "solar_charger.yaml").read_text(encoding="utf-8"))
    charts = [c for c in _cards(dash) if c.get("type") == "custom:apexcharts-card"]
    assert charts
    for chart in charts:
        assert set(chart) <= APEX_CARD_KEYS, set(chart) - APEX_CARD_KEYS
        if any("stack_group" in s for s in chart["series"]):
            assert chart.get("stacked") is True                      # stack_group exige stacked: true
        for key in ("header", "span"):
            assert set(chart.get(key, {})) <= APEX_NESTED[key]
        for axis in chart.get("yaxis", []):
            assert set(axis) <= APEX_NESTED["yaxis"]
        names = [s.get("name") for s in chart["series"]]
        assert len(names) == len(set(names))                         # nombres únicos (bug de apexcharts)
        for series in chart["series"]:
            assert set(series) <= APEX_SERIES_KEYS, set(series) - APEX_SERIES_KEYS
            for key in ("group_by", "statistics", "show"):
                assert set(series.get(key, {})) <= APEX_NESTED[key]
            assert "color_threshold" not in series or chart.get("experimental", {}).get("color_threshold")
