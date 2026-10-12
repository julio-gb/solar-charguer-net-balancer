"""Precio de la energía según día (laborable/festivo) y hora."""
from __future__ import annotations

from datetime import datetime

from .config import Config


class Tariff:
    def __init__(self, config: Config):
        self._periods = config.tariff_periods
        self._holidays = config.holidays

    def is_workday(self, when: datetime, workday_override: bool | None = None) -> bool:
        """Laborable = lunes a viernes no festivo. Un sensor Workday de HA tiene prioridad."""
        if workday_override is not None:
            return workday_override
        return when.weekday() < 5 and when.date() not in self._holidays

    def price_at(self, when: datetime, workday_override: bool | None = None) -> float | None:
        kind = "laborable" if self.is_workday(when, workday_override) else "festivo"
        minute = when.hour * 60 + when.minute
        for period in self._periods:
            if period.days == kind and period.start_min <= minute < period.end_min:
                return period.price
        return None
