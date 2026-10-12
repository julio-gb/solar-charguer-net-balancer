"""Carga y validación de la configuración del addon (/data/options.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

OPTIONS_PATH = Path("/data/options.json")


@dataclass(frozen=True)
class TariffPeriod:
    days: str  # "laborable" | "festivo"
    start_min: int  # minutos desde 00:00
    end_min: int  # minutos desde 00:00 (1440 = 24:00)
    price: float  # €/kWh


@dataclass(frozen=True)
class Config:
    generation_power_entity: str
    home_power_entity: str
    charger_power_entity: str
    generation_energy_entity: str
    home_energy_entity: str
    charger_energy_entity: str
    charger_switch_entity: str
    charger_current_entity: str
    car_soc_entity: str = ""
    workday_entity: str = ""
    voltage: int = 230
    min_current: int = 6
    max_current: int = 21
    poll_interval_seconds: int = 30
    decision_interval_minutes: int = 5
    end_of_hour_window_minutes: int = 10
    hour_close_delay_minutes: int = 10
    safety_margin_wh: int = 50
    min_on_minutes: int = 5
    min_off_minutes: int = 5
    disconnect_tolerance_seconds: int = 120
    disconnect_notify_minutes: int = 15
    coverage_target_percent: int = 60
    compensation_price: float = 0.02
    car_battery_kwh: float = 46.0
    charging_efficiency: float = 0.9
    holidays: frozenset[date] = field(default_factory=frozenset)
    tariff_periods: tuple[TariffPeriod, ...] = ()
    log_level: str = "info"


class ConfigError(ValueError):
    pass


def _hhmm_to_min(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_config(raw: dict) -> Config:
    required = [
        "generation_power_entity",
        "home_power_entity",
        "charger_power_entity",
        "generation_energy_entity",
        "home_energy_entity",
        "charger_energy_entity",
        "charger_switch_entity",
        "charger_current_entity",
    ]
    missing = [key for key in required if not str(raw.get(key) or "").strip()]
    if missing:
        raise ConfigError(f"Faltan entidades obligatorias: {', '.join(missing)}")

    periods = []
    for item in raw.get("tariff_periods") or []:
        start, end = _hhmm_to_min(item["start"]), _hhmm_to_min(item["end"])
        if end <= start:
            raise ConfigError(f"Tramo de tarifa inválido {item['start']}-{item['end']}")
        periods.append(TariffPeriod(item["days"], start, end, float(item["price"])))
    if not periods:
        raise ConfigError("Debe definirse al menos un tramo de tarifa")

    min_current = int(raw.get("min_current", 6))
    max_current = int(raw.get("max_current", 21))
    if max_current < min_current:
        raise ConfigError("max_current debe ser mayor o igual que min_current")

    known = {f for f in Config.__dataclass_fields__}
    values = {k: v for k, v in raw.items() if k in known}
    for key in ("car_soc_entity", "workday_entity"):
        values[key] = str(values.get(key) or "").strip()
    values["holidays"] = frozenset(date.fromisoformat(d) for d in raw.get("holidays") or [])
    values["tariff_periods"] = tuple(periods)
    return Config(**values)


def load_config(path: Path = OPTIONS_PATH) -> Config:
    return parse_config(json.loads(path.read_text(encoding="utf-8")))
