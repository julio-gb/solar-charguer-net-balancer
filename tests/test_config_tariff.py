from datetime import datetime

import pytest

from solar_balancer.config import ConfigError, parse_config
from solar_balancer.tariff import Tariff

from helpers import default_options, make_config


def test_default_options_parse():
    cfg = make_config()
    assert cfg.max_current == 21 and cfg.min_current == 6
    assert cfg.compensation_price == 0.02
    assert len(cfg.tariff_periods) == 7


def test_missing_entity_rejected():
    options = default_options()
    options["charger_switch_entity"] = ""
    with pytest.raises(ConfigError):
        parse_config(options)


@pytest.mark.parametrize("when,price", [
    (datetime(2026, 10, 12, 3, 0), 0.087),    # lunes valle
    (datetime(2026, 10, 12, 9, 30), 0.119),   # lunes llano
    (datetime(2026, 10, 12, 11, 0), 0.198),   # lunes punta
    (datetime(2026, 10, 12, 23, 59), 0.119),  # lunes 22-24
    (datetime(2026, 10, 10, 11, 0), 0.087),   # sábado
])
def test_prices(when, price):
    assert Tariff(make_config()).price_at(when) == price


def test_holiday_and_workday_sensor():
    tariff = Tariff(make_config(holidays=["2026-10-12"]))
    assert tariff.price_at(datetime(2026, 10, 12, 11, 0)) == 0.087
    assert tariff.price_at(datetime(2026, 10, 12, 11, 0), workday_override=True) == 0.198
