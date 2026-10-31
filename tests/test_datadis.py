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


def test_merge_hours_uses_meter_and_addon_solar():
    h = _hours(28, 3)
    hourly = {int(h[0].timestamp()): 1.0, int(h[1].timestamp()): 0.6}
    records = [HourRecord(h[0].isoformat(), 0.5, 0.6, 0.3, 0.2, 0.02),   # contador 1,0 frente a 0,9 del addon
               HourRecord(h[2].isoformat(), 0.0, 0.4, 0.0, 0.1, 0.02)]   # Datadis aún sin publicar
    recs, source = datadis.merge_hours(hourly, records, h[0], h[2] + timedelta(hours=1), lambda _: 0.15, 0.02, TZ)
    assert [source[int(x.timestamp())] for x in h] == ["contador", "sin_solar", "addon"]
    assert recs[0].consumption == pytest.approx(1.0) and recs[0].ev == 0.3 and recs[0].gen == 0.5
    assert recs[0].grid_import == pytest.approx(0.5)
    assert recs[1].gen == 0 and recs[1].home == 0.6 and recs[1].price == 0.15
    assert recs[2] is records[1]


def test_month_bill_with_meter_data():
    from helpers import make_config
    cfg = make_config()
    hourly, records = {}, []
    for day in (28, 29):
        for h in _hours(day):
            hourly[int(h.timestamp())] = 0.5
            records.append(HourRecord(h.isoformat(), 0, 0.4, 0.0, 0.1, 0.02))
    out = datadis.month_bill(hourly, records, NOW.date(), NOW, cfg, lambda _: 0.1, TZ)
    assert out["desde"] == "2026-10-28" and out["dias"][0]["fuente"] == "contador"
    assert out["importado_kwh"] == 24.0 and out["horas"] == {"contador": 48, "sin_solar": 0, "addon": 0}
    cmp = out["comparado"]
    assert cmp["contador"] == out["total"] and cmp["contador"] > cmp["addon"] and cmp["dif"] > 0
    assert sum(p["kwh"] for p in out["periodos"]) == pytest.approx(24.0)
    # Sin datos del contador en el mes no hay factura de Datadis.
    assert datadis.month_bill({}, records, NOW.date(), NOW, cfg, lambda _: 0.1, TZ) is None
