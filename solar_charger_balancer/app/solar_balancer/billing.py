"""Coste estimado de la factura eléctrica (2.0TD) a partir de los registros horarios.

Sigue el orden de la factura de Octopus:
  potencia + (energía − compensación) → impuesto eléctrico → + bono social y alquiler → IVA.
Si la compensación supera el coste de la energía, el sobrante se descuenta del total
(Solar Wallet).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .config import Config
from .energy import HourRecord

# Cuota mínima del impuesto eléctrico para uso no industrial: 1 €/MWh consumido.
ELECTRICITY_TAX_MIN_EUR_PER_KWH = 0.001


@dataclass
class Bill:
    days: float
    import_kwh: float
    export_kwh: float
    power: float  # término de potencia
    energy: float  # energía importada × precio de su hora
    compensation: float  # excedentes × compensación (sin impuestos)
    other: float  # bono social + alquiler de equipos
    electricity_tax: float
    vat: float
    wallet: float  # compensación que no cabe en la energía y se descuenta del total
    total: float

    def attributes(self) -> dict:
        r = lambda v: round(v, 2)  # noqa: E731
        return {"dias": self.days, "importado_kwh": round(self.import_kwh, 2), "vertido_kwh": round(self.export_kwh, 2),
                "potencia": r(self.power), "energia": r(self.energy), "compensacion": r(-self.compensation),
                "bono_social_y_alquiler": r(self.other), "impuesto_electrico": r(self.electricity_tax),
                "iva": r(self.vat), "solar_wallet": r(-self.wallet)}


def compute_bill(records: list[HourRecord], days: float, cfg: Config, with_compensation: bool = True) -> Bill:
    import_kwh = sum(r.grid_import for r in records)
    export_kwh = sum(r.grid_export for r in records)
    energy = sum(r.grid_import * r.price for r in records)
    compensation = sum(r.grid_export * r.compensation for r in records) if with_compensation else 0.0
    power = days * (cfg.contracted_power_p1_kw * cfg.power_price_p1 + cfg.contracted_power_p2_kw * cfg.power_price_p2)
    other = days * (cfg.social_bonus_per_day + cfg.meter_rental_per_day)
    net_energy = energy - compensation
    wallet = max(0.0, -net_energy)
    taxable = power + max(0.0, net_energy)
    electricity_tax = max(taxable * cfg.electricity_tax_percent / 100, import_kwh * ELECTRICITY_TAX_MIN_EUR_PER_KWH)
    vat = (taxable + electricity_tax + other) * cfg.vat_percent / 100
    total = taxable + electricity_tax + other + vat - wallet
    return Bill(days, import_kwh, export_kwh, power, energy, compensation, other, electricity_tax, vat, wallet, total)


def compensation_effect(records: list[HourRecord], days: float, cfg: Config) -> float:
    """Lo que los excedentes rebajan el total de la factura (impuestos incluidos)."""
    return compute_bill(records, days, cfg, False).total - compute_bill(records, days, cfg).total


def solar_value(records: list[HourRecord], cfg: Config) -> float:
    """Lo que habría costado la energía solar autoconsumida, al precio de su hora y con impuestos."""
    energy = sum(r.self_consumed * r.price for r in records)
    return energy * (1 + cfg.electricity_tax_percent / 100) * (1 + cfg.vat_percent / 100)


def _by_day(records: list[HourRecord]) -> dict[date, list[HourRecord]]:
    out: dict[date, list[HourRecord]] = {}
    for r in records:
        out.setdefault(r.start.date(), []).append(r)
    return out


def month_forecast(records: list[HourRecord], today: date, cfg: Config, base_days: int = 7) -> dict:
    """Coste por día del mes en curso y previsión de la factura del mes natural.

    La previsión suma lo ya consumido en días cerrados y estima el resto (hoy, los días que
    quedan y los días del mes sin datos) con la media de los últimos `base_days` días completos.
    """
    by_day = _by_day(records)
    rows, acum = [], 0.0
    for day in sorted(d for d in by_day if (d.year, d.month) == (today.year, today.month) and d <= today):
        bill = compute_bill(by_day[day], 1, cfg)
        fixed, energy = bill.power + bill.other, bill.energy - bill.compensation
        acum += bill.total
        rows.append({"d": day.isoformat(), "fijo": round(fixed, 2), "energia": round(energy, 2),
                     "impuestos": round(bill.total - fixed - energy, 2), "total": round(bill.total, 2),
                     "acum": round(acum, 2)})

    # Días completos recientes (≥ 22 horas registradas) como base de la media.
    base = [compute_bill(by_day[d], 1, cfg).total for d in sorted(by_day, reverse=True)
            if today - timedelta(days=base_days) <= d < today and len(by_day[d]) >= 22]
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    closed_rows = [r for r in rows if r["d"] < today.isoformat()]
    done = closed_rows[-1]["acum"] if closed_rows else 0.0
    missing = today.day - 1 - len(closed_rows)
    remaining = days_in_month - today.day + 1
    result = {"dias": rows, "prevision": [], "media_diaria": None, "dias_base": len(base),
              "dias_sin_datos": missing, "total": None}
    if not base:
        return result
    avg = sum(base) / len(base)
    points = [{"d": closed_rows[-1]["d"], "acum": done}] if closed_rows else []
    points += [{"d": (today + timedelta(days=k)).isoformat(), "acum": round(done + avg * (k + 1), 2)}
               for k in range(remaining)]
    result.update(prevision=points, media_diaria=round(avg, 2), total=done + avg * (remaining + missing))
    return result
