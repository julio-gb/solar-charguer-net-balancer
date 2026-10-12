from pathlib import Path

import yaml

from solar_balancer.config import parse_config

ROOT = Path(__file__).resolve().parents[1]


def default_options() -> dict:
    data = yaml.safe_load((ROOT / "solar_charger_balancer" / "config.yaml").read_text(encoding="utf-8"))
    options = dict(data["options"])
    options.update({
        "generation_power_entity": "sensor.pv_power",
        "home_power_entity": "sensor.home_power",
        "charger_power_entity": "sensor.ev_power",
        "generation_energy_entity": "sensor.pv_energy",
        "home_energy_entity": "sensor.home_energy",
        "charger_energy_entity": "sensor.ev_energy",
        "charger_start_entity": "switch.ev_charger",
        "charger_current_entity": "number.ev_current",
    })
    return options


def make_config(**overrides):
    options = default_options()
    options.update(overrides)
    return parse_config(options)
