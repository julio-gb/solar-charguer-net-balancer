"""Carga forzada puntual: ignora las reglas solares durante una ventana fija."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_FULL = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})\s*$")
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


class ScheduleError(ValueError):
    pass


def parse_start(text: str, now: datetime) -> datetime:
    """Acepta 'AAAA-MM-DD HH:MM' o 'HH:MM' (próxima vez que llegue esa hora)."""
    if m := _FULL.match(text or ""):
        day = datetime.fromisoformat(m.group(1))
        start = now.replace(year=day.year, month=day.month, day=day.day,
                            hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
    elif m := _TIME.match(text or ""):
        start = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if start <= now:
            start += timedelta(days=1)
    else:
        raise ScheduleError("Formato de inicio no válido. Usa 'AAAA-MM-DD HH:MM' o 'HH:MM'.")
    return start


@dataclass
class ForcedCharge:
    start: datetime
    end: datetime
    current_a: int

    @classmethod
    def create(cls, start: datetime, hours: float, current_a: int, now: datetime) -> "ForcedCharge":
        if hours <= 0:
            raise ScheduleError("La duración debe ser mayor que 0.")
        end = start + timedelta(hours=hours)
        if end <= now:
            raise ScheduleError("La carga programada ya habría terminado.")
        return cls(start, end, current_a)

    def is_active(self, now: datetime) -> bool:
        return self.start <= now < self.end

    def is_finished(self, now: datetime) -> bool:
        return now >= self.end

    def describe(self) -> str:
        return f"{self.start:%d/%m %H:%M} → {self.end:%d/%m %H:%M} · {self.current_a} A"

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "current_a": self.current_a}

    @classmethod
    def from_dict(cls, data: dict) -> "ForcedCharge":
        return cls(datetime.fromisoformat(data["start"]), datetime.fromisoformat(data["end"]), int(data["current_a"]))
