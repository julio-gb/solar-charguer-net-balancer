"""Lógica de decisión de carga basada en el balance neto horario.

Dos estrategias (cada ciclo, por defecto 5 min):

- «acumulado» (por defecto): solo se carga con energía ya vertida en la hora en curso.
  disponible = saldo_acumulado − margen + factor × excedente_actual × duración_del_ciclo
  Nunca se carga a cuenta de sol futuro, así que tolera datos solares atrasados y la
  caída de producción de la tarde.

- «prevision»: además del saldo, cuenta con el excedente previsto hasta el final de la hora.
  disponible = saldo_acumulado − margen + factor × excedente_actual × tiempo_restante
  Carga antes dentro de la hora, pero puede importar si el sol baja o sube el consumo.

En ambos casos se elige la intensidad para que la hora cierre con saldo ≥ 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

STRATEGIES = ("acumulado", "prevision")


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
    strategy: str = "acumulado"
    surplus_factor: float = 0.5


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
    margin = p.margin_wh / 1000.0
    in_end_window = minutes_left <= p.end_window_min

    balance = inp.hour_gen_kwh - inp.hour_home_kwh - inp.hour_ev_kwh
    # Sin dato solar o del hogar se asume que no habrá excedente (conservador).
    if inp.gen_kw is None or inp.home_kw is None:
        surplus_kw = 0.0
    else:
        surplus_kw = max(0.0, inp.gen_kw - inp.home_kw) * p.surplus_factor

    # Horizonte: hasta el siguiente ciclo (acumulado) o hasta el final de la hora (previsión).
    # En la ventana final siempre se mira hasta el cierre y solo con el saldo ya acumulado
    # si el coche no está cargando.
    if in_end_window:
        horizon = h_left
        future = 0.0 if not inp.charging else surplus_kw * h_left
    elif p.strategy == "prevision":
        horizon = h_left
        future = surplus_kw * h_left
    else:
        horizon = h_cycle
        future = surplus_kw * h_cycle
    available = balance - margin + future

    def amps_for(energy_kwh: float, hours: float) -> int:
        return int(energy_kwh / (hours * p.voltage / 1000.0)) if hours > 0 else 0

    def result(charge: bool, amps: int, reason: str, ev_hours: float) -> Decision:
        ev = kw_for(amps, p.voltage) * ev_hours if charge else 0.0
        forecast = balance + future - ev
        return Decision(charge, amps, reason, balance * 1000, forecast * 1000, available * 1000, minutes_left)

    amps = amps_for(available, horizon)
    if amps >= p.min_current:
        amps = min(amps, p.max_current)
        if in_end_window:
            reason = f"Últimos minutos: el saldo cubre {amps} A hasta el cierre"
        elif p.strategy == "prevision":
            reason = f"Previsión: excedente para {amps} A hasta el final de la hora"
        else:
            reason = f"Saldo acumulado suficiente para {amps} A"
        want = (True, amps, reason, horizon)
    elif p.strategy == "prevision" and not in_end_window and available >= kw_for(p.min_current, p.voltage) * h_cycle:
        want = (True, p.min_current, "Previsión: carga parcial a intensidad mínima", h_cycle)
    else:
        why = ("Últimos minutos: el saldo acumulado no cubre la carga hasta el cierre" if in_end_window
               else "Acumulando excedente en la hora" if p.strategy == "acumulado"
               else "Excedente insuficiente en la hora")
        want = (False, p.min_current, why, 0.0)

    charge, amps, reason, ev_hours = want

    # Tiempos mínimos para evitar arranques y paradas continuos.
    if inp.last_switch is not None and charge != inp.charging:
        elapsed = (inp.now - inp.last_switch).total_seconds() / 60.0
        limit = p.min_on_min if inp.charging else p.min_off_min
        # Mantener la carga solo si el saldo cubre lo que queda del tiempo mínimo; si no (p. ej. una
        # carga de los últimos minutos que cruza al empezar la hora siguiente), se para ya.
        hold_hours = max(0.0, limit - elapsed) / 60.0
        affordable = not inp.charging or available >= kw_for(inp.current_a, p.voltage) * hold_hours
        if elapsed < limit and affordable:
            keep_amps = inp.current_a if inp.charging else amps
            return result(inp.charging, keep_amps, f"Se mantiene el estado (tiempo mínimo {limit:g} min)",
                          h_cycle if inp.charging else 0.0)

    return result(charge, amps, reason, ev_hours)
