from datetime import datetime

from solar_balancer.energy import CounterTracker, HourRecord, compute_stats


def test_counter_increments_and_resets():
    c = CounterTracker()
    assert c.update(100.0) == 0.0
    assert round(c.update(100.4), 3) == 0.4
    assert c.update(None) == 0.0
    assert round(c.update(0.2), 3) == 0.2          # reinicio diario
    assert c.update(0.15) == 0.0                    # bajada pequeña: ignorada
    assert round(c.update(0.3), 3) == 0.1


def test_hour_record_metrics():
    r = HourRecord("2026-10-10T12:00:00+02:00", gen=1.0, home=0.3, ev=0.7, price=0.087, compensation=0.02)
    assert r.self_consumed == 1.0 and r.grid_import == 0.0
    assert round(r.ev_solar, 3) == 0.7
    assert round(r.savings, 4) == round(0.7 * 0.067, 4)
    night = HourRecord("2026-10-10T01:00:00+02:00", gen=0.0, home=0.3, ev=1.0, price=0.087, compensation=0.02)
    assert night.grid_import == 1.3 and night.ev_solar == 0.0


def test_coverage_stats():
    day = HourRecord("2026-10-10T12:00:00+02:00", 1.0, 0.3, 0.7, 0.087, 0.02)
    night = HourRecord("2026-10-10T01:00:00+02:00", 0.0, 0.5, 0.5, 0.087, 0.02)
    current = HourRecord("2026-10-10T13:00:00+02:00", 0.0, 0.0, 0.0, 0.087, 0.02)
    now = datetime.fromisoformat("2026-10-10T13:30:00+02:00")
    stats = compute_stats([night, day], current, now, 60)
    assert round(stats.coverage_today) == 50          # 1,0 solar / 2,0 consumo
    assert round(stats.ev_solar_share_today) == 58    # 0,7 / 1,2
    assert round(stats.kwh_to_target, 2) == 0.2       # 60 % de 2,0 − 1,0


def test_daily_history():
    from solar_balancer.energy import daily_history
    recs = [HourRecord("2026-10-16T12:00:00+02:00", 1.0, 0.2, 0.6, 0.119, 0.02),
            HourRecord("2026-10-16T22:00:00+02:00", 0.0, 0.2, 1.0, 0.119, 0.02),
            HourRecord("2026-09-01T12:00:00+02:00", 1.0, 0.2, 0.0, 0.119, 0.02)]   # fuera de los 30 días
    days = daily_history(recs, datetime.fromisoformat("2026-10-17T10:00:00+02:00"), 30)
    assert days == [{"d": "2026-10-16", "solar": 0.6, "red": 1.0, "cob": 40.0}]   # 0,8 solar / 2,0 consumo
