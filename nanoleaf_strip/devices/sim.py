"""A strip that only exists in software, for developing without hardware."""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from .base import BaseDevice


class SimDevice(BaseDevice):
    simulated = True

    def __init__(self, note: str = "Simulation (no hardware)", zones: int = 75):
        super().__init__()
        self.note = note
        self.length = zones

    def connect(self) -> Tuple[bool, str]:
        self.connected = True
        return True, self.note

    def close(self) -> None:
        self.connected = False

    def set_pixels(self, rgb: Sequence[Sequence[int]]) -> int:
        return 0

    def set_power(self, on: bool) -> None:
        pass

    def set_brightness(self, value: int) -> None:
        pass

    def info(self) -> Dict[str, object]:
        return {"model": "SIMULATED", "firmware": "-", "zones": self.length}
