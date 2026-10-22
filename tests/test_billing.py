import pytest

from solar_balancer.billing import compensation_effect, compute_bill, solar_value
from solar_balancer.energy import HourRecord

from helpers import make_config


def _rec(gen, home, price, comp=0.02, hour="2026-09-01T12:00:00+02:00"):
    return HourRecord(hour, gen, home, 0.0, price, comp)


def test_reproduces_octopus_invoice_september_2026():
    # Factura 01-09-2026 a 01-10-2026: punta 45,75 kWh, llano 50,77, valle 114,80, excedente 123,73 → 53,82 €.
    cfg = make_config()
    records = [_rec(0, 45.75, 0.1976), _rec(0, 50.77, 0.1186), _rec(0, 114.80, 0.0872), _rec(123.73, 0, 0.0872)]
    bill = compute_bill(records, 30, cfg)
    assert bill.power == pytest.approx(18.25, abs=0.01)
    assert bill.energy - bill.compensation == pytest.approx(22.60, abs=0.01)
    assert bill.other == pytest.approx(1.54, abs=0.01)
    assert bill.electricity_tax == pytest.approx(2.09, abs=0.01)
    assert bill.vat == pytest.approx(9.34, abs=0.01)
    assert bill.total == pytest.approx(53.82, abs=0.02)
    assert bill.wallet == 0


def test_surplus_beyond_energy_is_discounted_from_total():
    cfg = make_config()
    bill = compute_bill([_rec(0, 1, 0.1), _rec(100, 0, 0.1)], 1, cfg)
    assert bill.wallet == pytest.approx(2 - 0.1)
    no_surplus = compute_bill([_rec(0, 1, 0.1)], 1, cfg)
    assert compensation_effect([_rec(0, 1, 0.1), _rec(100, 0, 0.1)], 1, cfg) == pytest.approx(
        no_surplus.total - bill.total)


def test_compensation_effect_includes_taxes_when_it_fits_in_energy():
    cfg = make_config()
    records = [_rec(0, 10, 0.2), _rec(10, 0, 0.2)]  # 2 € de energía, 0,20 € de compensación
    assert compensation_effect(records, 1, cfg) == pytest.approx(0.2 * 1.0511269632 * 1.21)


def test_solar_value_uses_hour_price_and_taxes():
    cfg = make_config()
    records = [_rec(3, 2, 0.1976), _rec(1, 4, 0.0872)]  # 2 kWh y 1 kWh autoconsumidos
    expected = (2 * 0.1976 + 1 * 0.0872) * 1.0511269632 * 1.21
    assert solar_value(records, cfg) == pytest.approx(expected)


def test_month_forecast_uses_recent_complete_days():
    from datetime import date, datetime, timedelta

    from solar_balancer.billing import month_forecast

    cfg = make_config()
    start = datetime.fromisoformat("2026-10-12T00:00:00+02:00")
    # Del 12 al 21 de octubre: días completos de 24 h con 0,5 kWh por hora a 0,1 €/kWh; hoy (22) a medias.
    records = [HourRecord((start + timedelta(hours=h)).isoformat(), 0, 0.5, 0, 0.1, 0.02) for h in range(10 * 24 + 9)]
    fc = month_forecast(records, date(2026, 10, 22), cfg)
    day_cost = compute_bill(records[:24], 1, cfg).total
    assert fc["dias_base"] == 7 and fc["media_diaria"] == pytest.approx(day_cost, abs=0.01)
    assert fc["dias_sin_datos"] == 11                         # del 1 al 11 sin datos del addon
    assert fc["total"] == pytest.approx(31 * day_cost, abs=0.05)
    assert fc["prevision"][0]["d"] == "2026-10-21" and fc["prevision"][-1]["d"] == "2026-10-31"
    assert [r["d"] for r in fc["dias"]][-1] == "2026-10-22"
    row = fc["dias"][0]
    assert row["fijo"] + row["energia"] + row["impuestos"] == pytest.approx(row["total"], abs=0.02)
