from datetime import datetime, timedelta

from solar_balancer.controller import ControlInputs, ControlParams, decide

P = ControlParams(voltage=230, min_current=6, max_current=21, decision_interval_min=5,
                  end_window_min=10, margin_wh=50, min_on_min=5, min_off_min=5)
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
