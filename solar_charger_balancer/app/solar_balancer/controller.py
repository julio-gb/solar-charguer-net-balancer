"""Lógica de decisión de carga basada en el balance neto horario.

Cada ciclo (por defecto 5 min) se calcula la energía disponible para el coche hasta
el final de la hora de reloj:

    disponible = saldo_acumulado_hora + (P_generación − P_hogar) × tiempo_restante − margen

y se elige la intensidad para que la hora cierre con saldo ≥ 0 y lo más cerca de 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ControlParams:
    voltage: int
    min_current: int
    max_current: int
    decision_interval_min: float
    end_window_min: float
    margin_wh: float
    min_on_min: float
    min_off_min: float


@dataclass(frozen=True)
class ControlInputs:
    now: datetime
    hour_gen_kwh: float
    hour_home_kwh: float
    hour_ev_kwh: float
    gen_kw: float | None
    home_kw: float | None
    charging: bool  # estado deseado actual (encendido)
    current_a: int
    last_switch: datetime | None  # último arranque/parada ordenado por el addon


@dataclass(frozen=True)
class Decision:
    charge: bool
    current_a: int
    reason: str
    balance_wh: float
    forecast_wh: float
    available_wh: float
    minutes_left: float


def kw_for(current_a: int, voltage: int) -> float:
    return current_a * voltage / 1000.0


def minutes_left_in_hour(now: datetime) -> float:
    return 60.0 - (now.minute + now.second / 60.0)


def decide(inp: ControlInputs, p: ControlParams) -> Decision:
    minutes_left = minutes_left_in_hour(inp.now)
    h_left = minutes_left / 60.0
    h_cycle = min(h_left, p.decision_interval_min / 60.0)

    balance = inp.hour_gen_kwh - inp.hour_home_kwh - inp.hour_ev_kwh
    # Sin dato solar o del hogar se asume que no habrá excedente (conservador).
    if inp.gen_kw is None or inp.home_kw is None:
        surplus_kw = 0.0
    else:
        surplus_kw = inp.gen_kw - inp.home_kw
    rest = surplus_kw * h_left
    available = balance + rest - p.margin_wh / 1000.0

    p_min = kw_for(p.min_current, p.voltage)
    in_end_window = minutes_left <= p.end_window_min

    def result(charge: bool, amps: int, reason: str, ev_hours: float) -> Decision:
        forecast = balance + rest - (kw_for(amps, p.voltage) * ev_hours if charge else 0.0)
        return Decision(charge, amps, reason, balance * 1000, forecast * 1000, available * 1000, minutes_left)

    def amps_for(energy_kwh: float) -> int:
        return int(energy_kwh / (h_left * p.voltage / 1000.0)) if h_left > 0 else 0

    # En los últimos minutos solo se arranca con el saldo YA acumulado (sin previsión).
    amps_acc = amps_for(balance - p.margin_wh / 1000.0)
    amps_full = amps_for(available)

    if in_end_window and not inp.charging:
        if amps_acc >= p.min_current:
            amps = min(amps_acc, p.max_current)
            want = (True, amps, f"Últimos minutos: el saldo acumulado cubre {amps} A hasta el cierre", h_left)
        else:
            want = (False, p.min_current, "Últimos minutos: el saldo acumulado no cubre la carga hasta el cierre", 0.0)
    # 1) Intensidad que se puede mantener hasta el final de la hora.
    elif amps_full >= p.min_current:
        amps = min(amps_full, p.max_current)
        want = (True, amps, f"Excedente suficiente para {amps} A hasta el final de la hora", h_left)
    # 2) A intensidad mínima durante parte de la hora (al menos un ciclo).
    elif not in_end_window and available >= p_min * h_cycle:
        want = (True, p.min_current, "Carga parcial a intensidad mínima; se compensa en la hora", h_cycle)
    elif in_end_window and inp.charging and available >= p_min * h_cycle:
        want = (True, p.min_current, "Últimos minutos: el saldo aún cubre la carga", h_cycle)
    else:
        want = (False, p.min_current, "Excedente insuficiente en la hora", 0.0)

    charge, amps, reason, ev_hours = want

    # 3) Tiempos mínimos para evitar arranques y paradas continuos.
    if inp.last_switch is not None and charge != inp.charging:
        elapsed = (inp.now - inp.last_switch).total_seconds() / 60.0
        limit = p.min_on_min if inp.charging else p.min_off_min
        if elapsed < limit:
            keep_amps = inp.current_a if inp.charging else amps
            return result(inp.charging, keep_amps, f"Se mantiene el estado (tiempo mínimo {limit:g} min)", h_cycle if inp.charging else 0.0)

    return result(charge, amps, reason, ev_hours)
