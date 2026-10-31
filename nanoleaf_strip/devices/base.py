"""The interface the worker thread expects from any strip (real or simulated)."""
from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence, Tuple

from ..constants import DEFAULT_ZONES


class BaseDevice:
    simulated = False

    def __init__(self) -> None:
        self.connected = False
        self.length = DEFAULT_ZONES
        # Called with the raw payload of a physical-button event, from the worker thread.
        self.on_button: Optional[Callable[[bytes], None]] = None

    def connect(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def set_pixels(self, rgb: Sequence[Sequence[int]]) -> int:
        """Send one frame. Returns the device's status code (0 = accepted)."""
        raise NotImplementedError

    def set_power(self, on: bool) -> None:
        raise NotImplementedError

    def set_brightness(self, value: int) -> None:
        raise NotImplementedError

    def info(self) -> Dict[str, object]:
        return {"zones": self.length}
