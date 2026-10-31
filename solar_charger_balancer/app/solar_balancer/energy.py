"""Contadores de energía, balance horario y estadísticas de cobertura."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

# Un salto mayor que esto entre dos lecturas se considera un error del sensor.
MAX_DELTA_KWH = 10.0


class CounterTracker:
    """Convierte un sensor de energía acumulada (kWh) en incrementos.

    Tolera reinicios del contador (diarios o por sesión) y lecturas no disponibles. Si tras un
    aparente reinicio el valor vuelve al de antes, la caída fue un fallo de lectura (el sensor
    marcó 0 un instante) y solo cuenta lo que haya crecido de verdad.
    """

    def __init__(self, last: float | None = None):
        self.last = last
        self._before_reset: float | None = None  # valor anterior a un aparente reinicio

    def update(self, value: float | None) -> float:
        if value is None:
            return 0.0
        if self.last is None:
            self.last = value
            return 0.0
        if self._before_reset is not None:
            before = self._before_reset
            if value >= before:
                # Fallo de lectura: desde el reinicio ya se ha contado `last`.
                self._before_reset = None
                delta = value - before - self.last
                self.last = value
                return delta if 0 < delta <= MAX_DELTA_KWH else 0.0
            if value > before * 0.1:
                self._before_reset = None  # reinicio real: el contador sigue desde cero
        if value >= self.last:
            delta = value - self.last
            self.last = value
            return delta if delta <= MAX_DELTA_KWH else 0.0
        if value <= self.last * 0.1:
            # Reinicio del contador: lo acumulado desde el reinicio es el valor actual.
            self._before_reset = self.last
            self.last = value
            return value if value <= MAX_DELTA_KWH else 0.0
        # Bajada pequeña: lectura errónea, se ignora sin mover la referencia.
        return 0.0


@dataclass
class HourRecord:
    hour: str  # ISO de la hora de inicio (hora local)
    gen: float  # kWh
    home: float  # kWh
    ev: float  # kWh
    price: float  # €/kWh de red en esa hora
    compensation: float  # €/kWh de compensación

    @property
    def consumption(self) -> float:
        return self.home + self.ev

    @property
    def self_consumed(self) -> float:
        return min(self.gen, self.consumption)

    @property
    def grid_import(self) -> float:
        return max(0.0, self.consumption - self.gen)

    @property
    def grid_export(self) -> float:
        return max(0.0, self.gen - self.consumption)

    @property
    def balance(self) -> float:
        return self.gen - self.consumption

    @property
    def home_solar(self) -> float:
        """Energía del hogar cubierta por solar en el balance horario (el hogar va primero)."""
        return min(self.home, self.gen)

    @property
    def ev_solar(self) -> float:
        """Energía del coche cubierta por solar en el balance horario (el hogar va primero)."""
        return min(self.ev, max(0.0, self.gen - self.home))

    @property
    def savings(self) -> float:
        return self.ev_solar * max(0.0, self.price - self.compensation)

    @property
    def start(self) -> datetime:
        return datetime.fromisoformat(self.hour)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HourRecord":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


def _sum(records, attr):
    return sum(getattr(r, attr) for r in records)


def coverage(records) -> float | None:
    cons = _sum(records, "consumption")
    if cons <= 0:
        return None
    return 100.0 * _sum(records, "self_consumed") / cons


@dataclass
class Stats:
    coverage_today: float | None
    coverage_month: float | None
    coverage_year: float | None
    coverage_year_projection: float | None
    self_consumed_year: float
    consumption_year: float
    kwh_to_target: float
    ev_today: float
    ev_solar_share_today: float | None
    ev_month: float
    ev_solar_share_month: float | None
    savings_today: float
    savings_month: float
    savings_year: float


def compute_stats(records: list[HourRecord], current: HourRecord, now: datetime, target_pct: float) -> Stats:
    """Estadísticas de hoy, mes y año natural (incluye la hora en curso)."""
    year_recs = [r for r in records if r.start.year == now.year] + [current]
    month_recs = [r for r in year_recs if r.start.month == now.month]
    today_recs = [r for r in month_recs if r.start.date() == now.date()]

    self_year = _sum(year_recs, "self_consumed")
    cons_year = _sum(year_recs, "consumption")
    to_target = max(0.0, target_pct / 100.0 * cons_year - self_year)

    # Proyección simple: los días que quedan se comportan como la media de los últimos 30.
    window_start = now - timedelta(days=30)
    recent = [r for r in records if r.start >= window_start] + [current]
    days_recent = max(1.0, (now - max(window_start, min(r.start for r in recent))).total_seconds() / 86400)
    year_end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0)
    days_left = max(0.0, (year_end - now).total_seconds() / 86400)
    proj_self = self_year + _sum(recent, "self_consumed") / days_recent * days_left
    proj_cons = cons_year + _sum(recent, "consumption") / days_recent * days_left
    projection = 100.0 * proj_self / proj_cons if proj_cons > 0 else None

    def share(recs):
        ev = _sum(recs, "ev")
        return 100.0 * _sum(recs, "ev_solar") / ev if ev > 0 else None

    return Stats(
        coverage_today=coverage(today_recs),
        coverage_month=coverage(month_recs),
        coverage_year=coverage(year_recs),
        coverage_year_projection=projection,
        self_consumed_year=self_year,
        consumption_year=cons_year,
        kwh_to_target=to_target,
        ev_today=_sum(today_recs, "ev"),
        ev_solar_share_today=share(today_recs),
        ev_month=_sum(month_recs, "ev"),
        ev_solar_share_month=share(month_recs),
        savings_today=_sum(today_recs, "savings"),
        savings_month=_sum(month_recs, "savings"),
        savings_year=_sum(year_recs, "savings"),
    )


def _split(recs, tax_factor: float = 1.0) -> dict:
    """kWh con sol y de la red del total, del coche y del hogar, y lo que cuesta la energía
    importada de cada uno (precio de su hora × impuestos; sin potencia ni excedentes)."""
    out = {}
    for key, total, solar in (("total", "consumption", "self_consumed"), ("coche", "ev", "ev_solar"),
                              ("hogar", "home", "home_solar")):
        sol = _sum(recs, solar)
        out[f"{key}_solar"] = round(sol, 2)
        out[f"{key}_red"] = round(_sum(recs, total) - sol, 2)
        cost = sum((getattr(r, total) - getattr(r, solar)) * r.price for r in recs) * tax_factor
        out[f"{key}_red_eur"] = round(cost, 2)
    return out


def daily_history(records: list[HourRecord], now: datetime, days: int, tax_factor: float = 1.0) -> list[dict]:
    """Resumen por día de los últimos `days` días (incluido hoy, en curso) para las gráficas.

    «solar» y «red» son del coche (se mantienen por compatibilidad con dashboards anteriores).
    """
    first = (now - timedelta(days=days - 1)).date()
    by_day: dict = {}
    for r in records:
        day = r.start.date()
        if first <= day <= now.date():
            by_day.setdefault(day, []).append(r)
    out = []
    for day in sorted(by_day):
        recs = by_day[day]
        split = _split(recs, tax_factor)
        cov = coverage(recs)
        out.append({"d": day.isoformat(), "solar": split["coche_solar"], "red": split["coche_red"],
                    "cob": None if cov is None else round(cov, 1), **split})
    return out


def month_split(records: list[HourRecord], now: datetime, tax_factor: float = 1.0) -> dict:
    """Reparto por origen del mes natural en curso."""
    return _split([r for r in records if (r.start.year, r.start.month) == (now.year, now.month)], tax_factor)
