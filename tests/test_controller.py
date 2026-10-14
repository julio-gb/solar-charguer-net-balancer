from dataclasses import replace
from datetime import datetime, timedelta

from solar_balancer.controller import ControlInputs, ControlParams, decide

A = ControlParams(voltage=230, min_current=6, max_current=21, decision_interval_min=5,
                  end_window_min=10, margin_wh=50, min_on_min=5, min_off_min=5)   # acumulado (defecto)
P = replace(A, strategy="prevision", surplus_factor=1.0)
T0 = datetime(2026, 10, 10, 13, 0)


def inp(minute=0, gen=0.0, home=0.0, ev=0.0, gen_kw=0.0, home_kw=0.0, charging=False, amps=6, last=None):
    return ControlInputs(T0 + timedelta(minutes=minute), gen, home, ev, gen_kw, home_kw, charging, amps, last)


def test_small_surplus_charges_part_of_hour():
    d = decide(inp(gen_kw=1.0, home_kw=0.3), P)
    assert d.charge and d.current_a == 6


def test_large_surplus_scales_current():
    d = decide(inp(gen_kw=3.3, home_kw=0.3), P)
    assert d.charge and d.current_a == 12   # (3,0 − 0,05) kWh / 0,23 kW


def test_current_capped_at_max():
    assert decide(inp(gen_kw=9.0, home_kw=0.0), P).current_a == 21


def test_no_solar_data_is_conservative():
    d = decide(inp(gen_kw=None, home_kw=0.3), P)
    assert not d.charge


def test_end_window_only_starts_with_accumulated_balance():
    assert not decide(inp(minute=52, gen=0.3, home=0.2, gen_kw=2.0, home_kw=0.2), P).charge
    d = decide(inp(minute=52, gen=0.9, home=0.2, gen_kw=0.0, home_kw=0.2), P)
    assert d.charge and d.current_a >= 6


def test_min_on_time_holds_state():
    d = decide(inp(minute=20, gen=0.0, home=0.5, gen_kw=0.0, home_kw=0.5, charging=True,
                   last=T0 + timedelta(minutes=18)), P)
    assert d.charge


def test_simulated_hour_closes_without_import():
    """0,7 kW de excedente constante: debe cargar parte de la hora y cerrar con saldo ≥ 0."""
    gen_kw, home_kw = 1.0, 0.3
    gen = home = ev = 0.0
    charging, amps, last = False, 6, None
    for minute in range(0, 60, 5):
        d = decide(inp(minute, gen, home, ev, gen_kw, home_kw, charging, amps, last), P)
        if d.charge != charging:
            last = T0 + timedelta(minutes=minute)
        charging, amps = d.charge, d.current_a
        step = 5 / 60
        gen += gen_kw * step
        home += home_kw * step
        ev += (amps * 0.23 if charging else 0.0) * step
    assert ev > 0.3
    assert gen - home - ev >= 0


# ---------------------------------------------------------------- estrategia «acumulado»
def test_accumulated_waits_for_balance_at_hour_start():
    assert not decide(inp(gen_kw=1.5, home_kw=0.3), A).charge          # saldo 0: espera


def test_accumulated_charges_once_balance_exists():
    d = decide(inp(minute=15, gen=0.45, home=0.08, gen_kw=1.5, home_kw=0.3), A)
    assert d.charge and d.current_a >= 6


def simulate(params, sun, home_kw):
    """Hora simulada en pasos de 5 min con producción y consumo variables. Devuelve (saldo, coche)."""
    gen = home = ev = 0.0
    charging, amps, last = False, 6, None
    for i, minute in enumerate(range(0, 60, 5)):
        # El addon ve los datos con 5 min de retraso (FusionSolar).
        seen_gen, seen_home = sun[max(0, i - 1)], home_kw[max(0, i - 1)]
        d = decide(inp(minute, gen, home, ev, seen_gen, seen_home, charging, amps, last), params)
        if d.charge != charging:
            last = T0 + timedelta(minutes=minute)
        charging, amps = d.charge, d.current_a
        step = 5 / 60
        gen += sun[i] * step
        home += home_kw[i] * step
        ev += (amps * 0.23 if charging else 0.0) * step
    return gen - home - ev, ev


AFTERNOON_SUN = [1.2, 1.15, 1.1, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.45, 0.4, 0.35]
COOKING = [0.3, 2.0, 2.2, 1.5, 0.4, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]


def test_afternoon_with_cooking_accumulated_never_imports():
    balance, ev = simulate(A, AFTERNOON_SUN, COOKING)
    assert balance >= 0


def test_afternoon_with_cooking_forecast_can_import():
    balance, _ = simulate(P, AFTERNOON_SUN, COOKING)
    assert balance < 0          # el problema observado el 14/10


def test_accumulated_still_charges_on_steady_surplus():
    balance, ev = simulate(A, [1.5] * 12, [0.3] * 12)
    assert balance >= 0 and ev > 0.6
