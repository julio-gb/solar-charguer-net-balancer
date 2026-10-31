import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from solar_balancer import datadis
from solar_balancer.energy import HourRecord

TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=TZ)


def test_find_consumption_statistic_ignores_periods():
    ids = ["edata:13kd_p1_consumption", "sensor.x", "edata:13kd_consumption", "edata:13kd_surplus"]
    assert datadis.find_consumption_statistic(ids) == "edata:13kd_consumption"
    assert datadis.find_consumption_statistic(["sensor.x"]) is None
    assert datadis.maximeter_ids("edata:13kd_consumption")["p2"] == "edata:13kd_p2_maximeter"


def _hours(day, n=24):
    start = datetime(2026, 10, day, 0, 0, tzinfo=TZ)
    return [start + timedelta(hours=h) for h in range(n)]


def test_compare_only_matched_hours_and_complete_days():
    rec = datadis.Reconciliation(statistic_id="edata:x_consumption")
    records = []
    for h in _hours(28):                                   # día completo: addon 0,48 vs Datadis 0,50 por hora
        rec.hourly[int(h.timestamp())] = 0.5
        records.append(HourRecord(h.isoformat(), 0, 0.4, 0.08, 0.1, 0.02))
    for h in _hours(29, 10):                               # día incompleto en el addon: no se compara
        rec.hourly[int(h.timestamp())] = 0.5
        records.append(HourRecord(h.isoformat(), 0, 0.5, 0, 0.1, 0.02))
    for h in _hours(29)[10:]:
        rec.hourly[int(h.timestamp())] = 0.5
    pct, attrs = rec.compare(records, NOW, TZ)
    assert [d["d"] for d in attrs["dias"]] == ["2026-10-28"]
    assert attrs["dias"][0]["datadis"] == 12 and attrs["dias"][0]["addon"] == pytest.approx(11.52)
    assert pct == -4.0 and attrs["mes"]["dif_pct"] == -4.0
    assert attrs["ultimo_dato"].startswith("2026-10-29T23:00")


class FakeHA:
    def __init__(self):
        self.calls = []

    async def ws_command(self, msg):
        self.calls.append(msg)
        if msg["type"] == "recorder/list_statistic_ids":
            return [{"statistic_id": "edata:13kd_p1_consumption"}, {"statistic_id": "edata:13kd_consumption"}]
        start = int(datetime(2026, 10, 28, 1, 0, tzinfo=TZ).timestamp() * 1000)
        if msg["period"] == "hour":
            return {"edata:13kd_consumption": [{"start": start, "change": 0.3}, {"start": start + 3600000, "change": None}]}
        month = int(datetime(2026, 9, 1, tzinfo=TZ).timestamp() * 1000)
        return {"edata:13kd_p2_maximeter": [{"start": month, "max": 4.342}]}


def test_fetch_reads_hourly_consumption_and_maximeter():
    ha = FakeHA()
    rec = asyncio.run(datadis.fetch(ha, NOW, TZ))
    assert rec.statistic_id == "edata:13kd_consumption" and rec.error is None
    assert list(rec.hourly.values()) == [0.3]
    assert rec.maximeter == [{"mes": "2026-09", "p2": 4.34}]
    assert ha.calls[1]["statistic_ids"] == ["edata:13kd_consumption"]


def test_fetch_without_edata_reports_error():
    class Empty:
        async def ws_command(self, msg):
            return []
    rec = asyncio.run(datadis.fetch(Empty(), NOW, TZ))
    assert rec.error and rec.hourly == {}
