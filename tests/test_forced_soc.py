from datetime import datetime

import pytest

from solar_balancer.forced import ForcedCharge, ScheduleError, parse_start
from solar_balancer.soc import SocEstimator

NOW = datetime(2026, 10, 12, 20, 0)


def test_parse_start_formats():
    assert parse_start("2026-10-13 00:00", NOW) == datetime(2026, 10, 13, 0, 0)
    assert parse_start("00:00", NOW) == datetime(2026, 10, 13, 0, 0)
    assert parse_start("21:30", NOW) == datetime(2026, 10, 12, 21, 30)
    with pytest.raises(ScheduleError):
        parse_start("mañana", NOW)


def test_forced_window_fixed_end():
    f = ForcedCharge.create(datetime(2026, 10, 13, 0, 0), 4, 21, NOW)
    assert not f.is_active(NOW)
    assert f.is_active(datetime(2026, 10, 13, 3, 59))
    assert f.is_finished(datetime(2026, 10, 13, 4, 0))
    assert ForcedCharge.from_dict(f.to_dict()) == f


def test_soc_estimate():
    s = SocEstimator(46, 0.9)
    assert s.estimate(0) is None
    assert s.update_real(48, "t1", 10.0)
    assert not s.update_real(48, "t1", 11.0)
    assert round(s.estimate(12.6)) == 53     # 48 + 2,6 × 0,9 / 46
    assert s.estimate(200) == 100.0
