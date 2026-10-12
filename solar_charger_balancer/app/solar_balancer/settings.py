"""Ajustes editables desde la página web del addon.

Los valores de la configuración del addon (/data/options.json) actúan como valores
iniciales; lo guardado desde la página (/data/settings.json) tiene prioridad.
"""
from __future__ import annotations

import json
from datetime import date
import os
from pathlib import Path

from .config import OPTIONS_PATH, Config, parse_config

SETTINGS_PATH = Path("/data/settings.json")

POWER_UNITS = ["W", "kW", "MW"]
ENERGY_UNITS = ["Wh", "kWh", "MWh"]


def _entity(key, label, help_, domains, units=None, device_classes=None, required=True):
    return {"key": key, "label": label, "help": help_, "type": "entity", "domains": domains,
            "units": units or [], "device_classes": device_classes or [], "required": required}


def _num(key, label, help_, kind, minimum, maximum, step, unit=""):
    return {"key": key, "label": label, "help": help_, "type": kind, "min": minimum, "max": maximum,
            "step": step, "unit": unit}


# Definición de la página: secciones y campos. La página se genera a partir de esto.
SECTIONS = [
    {"title": "Placas y hogar", "fields": [
        _entity("generation_power_entity", "Potencia de las placas", "Potencia instantánea generada.", ["sensor"], POWER_UNITS, ["power"]),
        _entity("generation_energy_entity", "Energía generada acumulada", "Contador de energía de las placas.", ["sensor"], ENERGY_UNITS, ["energy"]),
        _entity("home_power_entity", "Potencia del hogar", "Consumo del hogar sin incluir el cargador.", ["sensor"], POWER_UNITS, ["power"]),
        _entity("home_energy_entity", "Energía del hogar acumulada", "Contador del hogar sin incluir el cargador.", ["sensor"], ENERGY_UNITS, ["energy"]),
    ]},
    {"title": "Cargador", "fields": [
        _entity("charger_power_entity", "Potencia del cargador", "Potencia que consume el cargador.", ["sensor"], POWER_UNITS, ["power"]),
        _entity("charger_energy_entity", "Energía del cargador acumulada", "Contador de energía del cargador.", ["sensor"], ENERGY_UNITS, ["energy"]),
        _entity("charger_switch_entity", "Interruptor de carga", "Inicia y detiene la carga.", ["switch", "input_boolean"]),
        _entity("charger_current_entity", "Intensidad del cargador", "Intensidad máxima de carga.", ["number", "input_number"], ["A"], ["current"]),
        _num("voltage", "Tensión", "Tensión de la instalación.", "int", 100, 400, 1, "V"),
        _num("min_current", "Intensidad mínima", "Mínimo que admite el cargador.", "int", 1, 32, 1, "A"),
        _num("max_current", "Intensidad máxima", "Límite configurado en el cargador.", "int", 1, 32, 1, "A"),
    ]},
    {"title": "Coche y calendario", "fields": [
        _entity("car_soc_entity", "Batería del coche", "Opcional. Se usa como punto de partida de la estimación.", ["sensor"], ["%"], ["battery"], required=False),
        _num("car_battery_kwh", "Capacidad útil de la batería", "", "float", 1, 200, 0.1, "kWh"),
        _num("charging_efficiency", "Eficiencia de carga", "Fracción de la energía que llega a la batería.", "float", 0.5, 1, 0.01, ""),
        _entity("workday_entity", "Sensor de día laborable", "Opcional (integración Workday). Tiene prioridad sobre la lista de festivos.", ["binary_sensor"], required=False),
        {"key": "holidays", "label": "Festivos", "help": "Días que se facturan como fin de semana.", "type": "dates"},
    ]},
    {"title": "Tarifa", "fields": [
        {"key": "tariff_periods", "label": "Tramos de precio", "help": "Precios sin impuestos. «Festivo» incluye fines de semana y festivos.", "type": "tariffs"},
        _num("compensation_price", "Compensación de excedentes", "Lo que te pagan por cada kWh vertido.", "float", 0, 1, 0.001, "€/kWh"),
    ]},
    {"title": "Objetivo", "fields": [
        _num("coverage_target_percent", "Cobertura solar anual objetivo", "Energía solar autoconsumida ÷ consumo total (hogar + cargador).", "int", 1, 100, 1, "%"),
    ]},
    {"title": "Control", "fields": [
        _num("decision_interval_minutes", "Intervalo de decisión", "Cada cuánto se recalcula la carga.", "int", 1, 30, 1, "min"),
        _num("poll_interval_seconds", "Intervalo de lectura", "Cada cuánto se leen las entidades.", "int", 10, 300, 1, "s"),
        _num("end_of_hour_window_minutes", "Ventana final de la hora", "En estos minutos solo se arranca con el saldo ya acumulado.", "int", 0, 30, 1, "min"),
        _num("hour_close_delay_minutes", "Retraso de cierre de hora", "Tiempo para recibir lecturas tardías tras el cambio de hora.", "int", 0, 30, 1, "min"),
        _num("safety_margin_wh", "Margen de seguridad", "Energía que se reserva en cada hora.", "int", 0, 1000, 10, "Wh"),
        _num("min_on_minutes", "Tiempo mínimo encendido", "", "int", 0, 60, 1, "min"),
        _num("min_off_minutes", "Tiempo mínimo apagado", "", "int", 0, 60, 1, "min"),
    ]},
    {"title": "Conexión del cargador", "fields": [
        _num("disconnect_tolerance_seconds", "Tolerancia a microcortes", "Cortes más cortos no se registran como incidencia.", "int", 0, 3600, 10, "s"),
        _num("disconnect_notify_minutes", "Avisar tras", "Notificación en HA si el corte dura más.", "int", 1, 1440, 1, "min"),
        {"key": "log_level", "label": "Nivel de registro", "help": "", "type": "select", "options": ["debug", "info", "warning", "error"]},
    ]},
]

FIELD_KEYS = [f["key"] for s in SECTIONS for f in s["fields"]]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def load_raw(options_path: Path | None = None, settings_path: Path | None = None) -> dict:
    """Configuración efectiva sin validar: opciones del addon + ajustes guardados."""
    raw = _read_json(options_path or OPTIONS_PATH)
    raw.update(_read_json(settings_path or SETTINGS_PATH))
    return raw


def validate(raw: dict) -> Config:
    return parse_config(raw)


def save_raw(raw: dict, settings_path: Path | None = None) -> None:
    settings_path = settings_path or SETTINGS_PATH
    data = {k: raw[k] for k in FIELD_KEYS if k in raw}
    tmp = settings_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, settings_path)


def _hhmm(value: str, allow_24: bool) -> int:
    hours, minutes = str(value).strip().split(":")
    total = int(hours) * 60 + int(minutes)
    if not (0 <= int(minutes) < 60) or total < 0 or total > 1440 or (total == 1440 and not allow_24):
        raise ValueError
    return total


def check(raw: dict) -> tuple[dict, dict[str, str]]:
    """Normaliza los tipos y valida rangos. Devuelve (valores limpios, errores por campo)."""
    clean, errors = dict(raw), {}
    for section in SECTIONS:
        for f in section["fields"]:
            key, kind, value = f["key"], f["type"], raw.get(f["key"])
            try:
                if kind == "entity":
                    clean[key] = str(value or "").strip()
                    if f["required"] and not clean[key]:
                        errors[key] = "Selecciona una entidad."
                elif kind in ("int", "float"):
                    number = int(value) if kind == "int" else float(value)
                    if kind == "int" and float(value) != number:
                        raise ValueError
                    if not f["min"] <= number <= f["max"]:
                        errors[key] = f"Debe estar entre {f['min']} y {f['max']}."
                    clean[key] = number
                elif kind == "select":
                    if value not in f["options"]:
                        errors[key] = "Valor no válido."
                elif kind == "dates":
                    clean[key] = sorted({date.fromisoformat(str(d)).isoformat() for d in (value or [])})
                elif kind == "tariffs":
                    clean[key] = _check_tariffs(value or [])
            except (TypeError, ValueError) as err:
                errors[key] = str(err) if isinstance(err, TariffError) else "Valor no válido."
    if not errors and clean["max_current"] < clean["min_current"]:
        errors["max_current"] = "Debe ser mayor o igual que la intensidad mínima."
    return clean, errors


class TariffError(ValueError):
    pass


def _check_tariffs(rows: list) -> list[dict]:
    out, by_day = [], {"laborable": [], "festivo": []}
    for i, row in enumerate(rows, 1):
        days = row.get("days")
        if days not in by_day:
            raise TariffError(f"Tramo {i}: tipo de día no válido.")
        try:
            start, end = _hhmm(row.get("start"), False), _hhmm(row.get("end"), True)
            price = float(row.get("price"))
        except (TypeError, ValueError, AttributeError):
            raise TariffError(f"Tramo {i}: hora o precio no válidos.") from None
        if end <= start or price < 0:
            raise TariffError(f"Tramo {i}: el fin debe ser posterior al inicio y el precio ≥ 0.")
        by_day[days].append((start, end))
        out.append({"days": days, "start": row["start"].strip(), "end": row["end"].strip(), "price": price})
    for days, spans in by_day.items():
        spans.sort()
        covered = 0
        for start, end in spans:
            if start != covered:
                raise TariffError(f"Tramos «{days}»: " + ("se solapan." if start < covered else
                                  f"falta precio entre {covered // 60:02d}:{covered % 60:02d} y {start // 60:02d}:{start % 60:02d}."))
            covered = end
        if covered != 1440:
            raise TariffError(f"Tramos «{days}»: deben cubrir hasta las 24:00.")
    return out
