"""Conciliación con los datos de la distribuidora (Datadis) que guarda la integración e-data.

e-data guarda en las estadísticas de HA el consumo horario del contador
(`edata:<cups>_consumption`) y la potencia máxima registrada por el maxímetro
(`edata:<cups>_p1_maximeter` / `_p2_maximeter`). Se compara, hora a hora, con el consumo
que mide el addon (hogar + cargador). Datadis publica los datos con 1–2 días de retraso.

También calcula la factura con el consumo del contador: en cada hora se toma el consumo de
Datadis y la generación asignada que mide el addon (Datadis no trae el reparto del autoconsumo
compartido). Las horas anteriores al addon toman la generación de las estadísticas de HA del
sensor de energía generada, y las que Datadis aún no ha publicado se completan con el addon.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .billing import compute_bill
from .config import Config
from .energy import HourRecord

# Días que se consultan y se muestran.
DAYS = 45
SHOWN_DAYS = 30
# Un día se compara solo si el addon tiene casi todas sus horas.
MIN_HOURS_PER_DAY = 22
PERIOD_NAMES = ("Punta", "Llano", "Valle")
MIN_GENERATION_PER_DAY = 0.1  # kWh


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
    generation: dict[int, float] = field(default_factory=dict)  # generación según las estadísticas de HA
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


def merge_hours(hourly: dict[int, float], records: list[HourRecord], start: datetime, end: datetime,
                price_at: Callable[[datetime], float], compensation: float, tz: ZoneInfo,
                generation: dict[int, float] | None = None) -> tuple[list[HourRecord], dict[int, str]]:
    """Registros horarios de [start, end) con el consumo del contador y la solar del addon.

    Fuente de cada hora: «contador» (Datadis + solar del addon), «solar_ha» (Datadis + generación
    de las estadísticas de HA), «sin_solar» (solo Datadis: la generación se toma como 0) o
    «addon» (Datadis aún no la ha publicado).
    """
    generation = generation or {}
    addon = {int(r.start.timestamp()): r for r in records if start <= r.start < end}
    lo, hi = start.timestamp(), end.timestamp()
    out, source = [], {}
    for ts in sorted(set(addon) | {t for t in hourly if lo <= t < hi}):
        a, meter = addon.get(ts), hourly.get(ts)
        if meter is None:
            out.append(a)
            source[ts] = "addon"
        elif a is None:
            when = datetime.fromtimestamp(ts, tz)
            gen = generation.get(ts)
            out.append(HourRecord(when.isoformat(), gen or 0.0, meter, 0.0, price_at(when), compensation))
            source[ts] = "sin_solar" if gen is None else "solar_ha"
        else:
            # El contador manda en el total; el coche conserva lo que midió el cargador.
            ev = min(a.ev, meter)
            out.append(HourRecord(a.hour, a.gen, meter - ev, ev, a.price, a.compensation))
            source[ts] = "contador"
    return out, source


def _period_names(prices: list[float]) -> dict[float, str]:
    ranked = sorted(set(prices), reverse=True)
    if len(ranked) == len(PERIOD_NAMES):
        return dict(zip(ranked, PERIOD_NAMES))
    return {p: f"{p:.4f} €/kWh".replace(".", ",") for p in ranked}


def month_bill(hourly: dict[int, float], records: list[HourRecord], month: date, now: datetime, cfg: Config,
               price_at: Callable[[datetime], float], tz: ZoneInfo, daily: bool = True,
               generation: dict[int, float] | None = None) -> dict | None:
    """Factura del mes natural `month` con el consumo del contador (hasta `now`)."""
    start = datetime(month.year, month.month, 1, tzinfo=tz)
    end = datetime(month.year + month.month // 12, month.month % 12 + 1, 1, tzinfo=tz)
    recs, source = merge_hours(hourly, records, start, min(end, now), price_at, cfg.compensation_price, tz,
                               generation)
    if not any(s != "addon" for s in source.values()):
        return None
    first, last = recs[0].start.date(), recs[-1].start.date()
    days = (last - first).days + 1
    bill = compute_bill(recs, days, cfg)
    addon_recs = [r for r in records if start <= r.start < min(end, now)]
    # Comparación justa: mismas horas y mismos días de término fijo que tiene el addon.
    compared = None
    if addon_recs:
        a_days = (addon_recs[-1].start.date() - addon_recs[0].start.date()).days + 1
        hours = {int(r.start.timestamp()) for r in addon_recs}
        meter = compute_bill([r for r in recs if int(r.start.timestamp()) in hours], a_days, cfg).total
        addon = compute_bill(addon_recs, a_days, cfg).total
        compared = {"desde": addon_recs[0].start.date().isoformat(), "contador": round(meter, 2),
                    "addon": round(addon, 2), "dif": round(meter - addon, 2)}
    counts = {k: sum(1 for s in source.values() if s == k) for k in ("contador", "solar_ha", "sin_solar", "addon")}
    meter_hours = [ts for ts, s in source.items() if s != "addon"]

    names = _period_names([p.price for p in cfg.tariff_periods] or [r.price for r in recs])
    periods: dict[str, list[float]] = {}
    for r in recs:
        row = periods.setdefault(names.get(r.price, f"{r.price:.4f}"), [0.0, 0.0])
        row[0] += r.grid_import
        row[1] += r.grid_import * r.price
    order = list(dict.fromkeys(names.values()))
    result = {
        "mes": start.strftime("%Y-%m"), "desde": first.isoformat(), "hasta": last.isoformat(),
        "datadis_hasta": datetime.fromtimestamp(max(meter_hours) + 3600, tz).isoformat(timespec="minutes"),
        "total": round(bill.total, 2), **bill.attributes(),
        "consumo_kwh": round(sum(r.consumption for r in recs), 2),
        "comparado": compared,
        "horas": counts,
        "periodos": [{"periodo": k, "kwh": round(periods[k][0], 2), "eur": round(periods[k][1], 2)}
                     for k in sorted(periods, key=lambda k: order.index(k) if k in order else 99)],
    }
    if daily:
        by_day: dict[date, list[HourRecord]] = defaultdict(list)
        for r in recs:
            by_day[r.start.date()].append(r)
        addon_day: dict[date, list[HourRecord]] = defaultdict(list)
        for r in addon_recs:
            addon_day[r.start.date()].append(r)
        rows = []
        for day in sorted(by_day):
            kinds = {source[int(r.start.timestamp())] for r in by_day[day]}
            rows.append({"d": day.isoformat(), "total": round(compute_bill(by_day[day], 1, cfg).total, 2),
                         "addon": round(compute_bill(addon_day[day], 1, cfg).total, 2) if addon_day[day] else None,
                         "consumo": round(sum(r.consumption for r in by_day[day]), 2),
                         "importado": round(sum(r.grid_import for r in by_day[day]), 2),
                         "fuente": next(iter(kinds)) if len(kinds) == 1 else "mixta"})
        result["dias"] = rows
    return result


def _ms_to_dt(value, tz: ZoneInfo) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz)
    return datetime.fromisoformat(str(value)).astimezone(tz)


async def fetch(ha, now: datetime, tz: ZoneInfo, statistic_id: str = "", generation_id: str = "") -> Reconciliation:
    """Lee de las estadísticas de HA el consumo horario y el maxímetro mensual de e-data, y la
    generación horaria del sensor de energía generada (`generation_id`)."""
    rec = Reconciliation(updated=now.isoformat(timespec="seconds"))
    if not statistic_id:
        listing = await ha.ws_command({"type": "recorder/list_statistic_ids", "statistic_type": "sum"})
        statistic_id = find_consumption_statistic([s["statistic_id"] for s in listing or []]) or ""
    if not statistic_id:
        rec.error = "No se encuentra la estadística de consumo de e-data (integración Datadis)"
        return rec
    rec.statistic_id = statistic_id
    # Desde el día 1 del mes anterior (para su factura) o 45 días atrás si es antes.
    prev_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
    start = min(now - timedelta(days=DAYS), prev_month).replace(hour=0, minute=0, second=0, microsecond=0)
    hourly = await ha.ws_command({"type": "recorder/statistics_during_period", "start_time": start.isoformat(),
                                  "statistic_ids": [statistic_id], "period": "hour", "types": ["change"]})
    for row in (hourly or {}).get(statistic_id, []):
        if row.get("change") is not None:
            rec.hourly[int(_ms_to_dt(row["start"], tz).timestamp())] = max(0.0, float(row["change"]))
    if generation_id:
        gen = await ha.ws_command({"type": "recorder/statistics_during_period", "start_time": start.isoformat(),
                                   "statistic_ids": [generation_id], "period": "hour", "types": ["change"]})
        for row in (gen or {}).get(generation_id, []):
            if row.get("change") is not None:
                rec.generation[int(_ms_to_dt(row["start"], tz).timestamp())] = max(0.0, float(row["change"]))
        # Un día entero sin generación es un corte del sensor, no un día sin sol: se descarta.
        per_day: dict[date, float] = defaultdict(float)
        for ts, kwh in rec.generation.items():
            per_day[datetime.fromtimestamp(ts, tz).date()] += kwh
        rec.generation = {ts: kwh for ts, kwh in rec.generation.items()
                          if per_day[datetime.fromtimestamp(ts, tz).date()] >= MIN_GENERATION_PER_DAY}

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
