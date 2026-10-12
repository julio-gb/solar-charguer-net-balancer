"""Estimación del nivel de batería del coche entre lecturas reales."""
from __future__ import annotations


class SocEstimator:
    """Parte del último SoC real (el coche lo envía al apagarse) y suma la energía cargada."""

    def __init__(self, capacity_kwh: float, efficiency: float):
        self.capacity_kwh = capacity_kwh
        self.efficiency = efficiency
        self.anchor_soc: float | None = None
        self.anchor_ev_total: float = 0.0
        self.anchor_stamp: str | None = None

    def update_real(self, soc: float | None, stamp: str | None, ev_total_kwh: float) -> bool:
        """Registra una lectura real nueva (detectada por su marca de tiempo). Devuelve True si es nueva."""
        if soc is None or stamp is None or stamp == self.anchor_stamp:
            return False
        self.anchor_soc = soc
        self.anchor_ev_total = ev_total_kwh
        self.anchor_stamp = stamp
        return True

    def estimate(self, ev_total_kwh: float) -> float | None:
        if self.anchor_soc is None:
            return None
        added = max(0.0, ev_total_kwh - self.anchor_ev_total) * self.efficiency
        return min(100.0, self.anchor_soc + 100.0 * added / self.capacity_kwh)

    def to_dict(self) -> dict:
        return {"anchor_soc": self.anchor_soc, "anchor_ev_total": self.anchor_ev_total, "anchor_stamp": self.anchor_stamp}

    def load(self, data: dict) -> None:
        self.anchor_soc = data.get("anchor_soc")
        self.anchor_ev_total = data.get("anchor_ev_total", 0.0)
        self.anchor_stamp = data.get("anchor_stamp")
