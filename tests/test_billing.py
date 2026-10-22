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
