"""Conciliación con los datos de la distribuidora (Datadis) que guarda la integración e-data.

e-data guarda en las estadísticas de HA el consumo horario del contador
(`edata:<cups>_consumption`) y la potencia máxima registrada por el maxímetro
(`edata:<cups>_p1_maximeter` / `_p2_maximeter`). Se compara, hora a hora, con el consumo
que mide el addon (hogar + cargador). Datadis publica los datos con 1–2 días de retraso.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .energy import HourRecord

# Días que se consultan y se muestran.
DAYS = 45
SHOWN_DAYS = 30
# Un día se compara solo si el addon tiene casi todas sus horas.
MIN_HOURS_PER_DAY = 22


def find_consumption_statistic(statistic_ids: list[str]) -> str | None:
    """Estadística de consumo total de e-data (sin las de cada periodo)."""
    for sid in sorted(statistic_ids):
        if sid.startswith("edata:") and sid.endswith("_consumption") and not any(
                f"_p{n}_" in sid for n in (1, 2, 3)):
            return sid
    return None


def maximeter_ids(consumption_id: str) -> dict[str, str]:
    base = consumption_id[: -len("_consumption")]
    return {"p1": f"{base}_p1_maximeter", "p2": f"{base}_p2_maximeter"}


@dataclass
class Reconciliation:
    statistic_id: str | None = None
    updated: str | None = None
    error: str | None = None
    hourly: dict[int, float] = field(default_factory=dict)  # inicio de la hora (epoch s) → kWh
    maximeter: list[dict] = field(default_factory=list)

    def compare(self, records: list[HourRecord], now: datetime, tz: ZoneInfo) -> tuple[float | None, dict]:
        """(diferencia % de los últimos 30 días, atributos) comparando solo horas con ambos datos."""
        addon = {int(r.start.timestamp()): r.consumption for r in records}
        first = (now - timedelta(days=SHOWN_DAYS)).date()
        by_day: dict = defaultdict(lambda: [0.0, 0.0, 0])
        for ts, kwh in self.hourly.items():
            day = datetime.fromtimestamp(ts, tz).date()
            if day < first or ts not in addon:
                continue
            row = by_day[day]
            row[0] += kwh
            row[1] += addon[ts]
            row[2] += 1
        days = []
        for day in sorted(by_day):
            dd, aa, hours = by_day[day]
            if hours < MIN_HOURS_PER_DAY:
                continue
            days.append({"d": day.isoformat(), "datadis": round(dd, 2), "addon": round(aa, 2),
                         "dif": round(aa - dd, 2), "dif_pct": round(100 * (aa - dd) / dd, 1) if dd > 0 else None})

        def total(rows):
            dd = sum(r["datadis"] for r in rows)
            aa = sum(r["addon"] for r in rows)
            return {"dias": len(rows), "datadis": round(dd, 2), "addon": round(aa, 2),
                    "dif_pct": round(100 * (aa - dd) / dd, 1) if dd > 0 else None}

        month = [r for r in days if r["d"][:7] == now.strftime("%Y-%m")]
        last = max((datetime.fromtimestamp(ts, tz) for ts in self.hourly), default=None)
        summary = total(days)
        attrs = {"estadistica": self.statistic_id, "actualizado": self.updated, "error": self.error,
                 "ultimo_dato": last.isoformat() if last else None, "dias": days,
                 "periodo": summary, "mes": total(month), "maximetro": self.maximeter}
        return summary["dif_pct"], attrs


def _ms_to_dt(value, tz: ZoneInfo) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz)
    return datetime.fromisoformat(str(value)).astimezone(tz)


async def fetch(ha, now: datetime, tz: ZoneInfo, statistic_id: str = "") -> Reconciliation:
    """Lee de las estadísticas de HA el consumo horario y el maxímetro mensual de e-data."""
    rec = Reconciliation(updated=now.isoformat(timespec="seconds"))
    if not statistic_id:
        listing = await ha.ws_command({"type": "recorder/list_statistic_ids", "statistic_type": "sum"})
        statistic_id = find_consumption_statistic([s["statistic_id"] for s in listing or []]) or ""
    if not statistic_id:
        rec.error = "No se encuentra la estadística de consumo de e-data (integración Datadis)"
        return rec
    rec.statistic_id = statistic_id
    start = (now - timedelta(days=DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    hourly = await ha.ws_command({"type": "recorder/statistics_during_period", "start_time": start.isoformat(),
                                  "statistic_ids": [statistic_id], "period": "hour", "types": ["change"]})
    for row in (hourly or {}).get(statistic_id, []):
        if row.get("change") is not None:
            rec.hourly[int(_ms_to_dt(row["start"], tz).timestamp())] = max(0.0, float(row["change"]))

    ids = maximeter_ids(statistic_id)
    year_ago = (now - timedelta(days=365)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly = await ha.ws_command({"type": "recorder/statistics_during_period", "start_time": year_ago.isoformat(),
                                   "statistic_ids": list(ids.values()), "period": "month", "types": ["max"]})
    by_month: dict[str, dict] = {}
    for period, sid in ids.items():
        for row in (monthly or {}).get(sid, []):
            key = _ms_to_dt(row["start"], tz).strftime("%Y-%m")
            if row.get("max") is not None:
                by_month.setdefault(key, {"mes": key})[period] = round(float(row["max"]), 2)
    rec.maximeter = [by_month[k] for k in sorted(by_month)]
    return rec
