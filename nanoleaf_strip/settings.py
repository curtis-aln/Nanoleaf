"""Live, thread-safe settings plus JSON persistence.

`Settings` is an immutable snapshot. `SettingsStore` swaps in a new snapshot on every change,
so the engine, worker and GUI can each grab one without locking while they use it.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Optional, Tuple

from .constants import APP_NAME, IS_MAC, IS_WINDOWS
from .layout import CORNERS, Layout

log = logging.getLogger(__name__)

RGBT = Tuple[int, int, int]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _rgb(v, fallback: RGBT) -> RGBT:
    try:
        r, g, b = (int(_clamp(int(x), 0, 255)) for x in v)
        return (r, g, b)
    except (TypeError, ValueError):
        return fallback


@dataclass(frozen=True)
class Settings:
    effect: str = "Rainbow wave"
    color: RGBT = (0, 170, 255)
    color2: RGBT = (255, 70, 170)
    speed: float = 1.0
    brightness: int = 110
    power: bool = True
    # physical layout
    start: str = "tl"
    clockwise: bool = True
    offset: int = 0
    # safety
    on_exit: str = "off"          # "off" blanks + powers down the strip on quit, "leave" keeps the last frame
    max_brightness: int = 255     # hard ceiling on the hardware brightness value
    power_limit: float = 1.0      # 1.0 = off; lower values cap total LED current draw
    fade: float = 0.35            # seconds of crossfade when switching effects
    button_action: str = "cycle"  # what the strip's physical button does: "cycle" or "none"
    # screen mirror tuning
    screen_saturation: float = 1.25
    screen_response: float = 12.0  # higher = snappier colour changes
    screen_depth: float = 0.08     # how far in from the edge to sample (fraction of the screen)

    def layout(self) -> Layout:
        return Layout(self.start, self.clockwise, self.offset)

    def sanitised(self) -> "Settings":
        d = self
        return replace(
            d,
            effect=str(d.effect),
            color=_rgb(d.color, (0, 170, 255)),
            color2=_rgb(d.color2, (255, 70, 170)),
            speed=float(_clamp(float(d.speed), 0.1, 4.0)),
            brightness=int(_clamp(int(d.brightness), 1, 255)),
            power=bool(d.power),
            start=d.start if d.start in CORNERS else "tl",
            clockwise=bool(d.clockwise),
            offset=int(_clamp(int(d.offset), -500, 500)),
            on_exit=d.on_exit if d.on_exit in ("off", "leave") else "off",
            max_brightness=int(_clamp(int(d.max_brightness), 1, 255)),
            power_limit=float(_clamp(float(d.power_limit), 0.05, 1.0)),
            fade=float(_clamp(float(d.fade), 0.0, 3.0)),
            button_action=d.button_action if d.button_action in ("cycle", "none") else "cycle",
            screen_saturation=float(_clamp(float(d.screen_saturation), 0.0, 3.0)),
            screen_response=float(_clamp(float(d.screen_response), 1.0, 60.0)),
            screen_depth=float(_clamp(float(d.screen_depth), 0.02, 0.4)),
        )


def default_config_path() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME / "config.json"


def load_settings(path: Optional[Path]) -> Settings:
    """Read settings from disk. A missing file gives defaults; a corrupt one is set aside, not fatal."""
    if path is None or not Path(path).exists():
        return Settings()
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object")
        known = {f.name for f in fields(Settings)}
        kwargs = {k: v for k, v in raw.items() if k in known}
        for key in ("color", "color2"):
            if key in kwargs:
                kwargs[key] = tuple(kwargs[key])
        return Settings(**kwargs).sanitised()
    except (OSError, ValueError, TypeError) as e:
        bad = path.with_suffix(".bad")
        log.warning("Could not read %s (%s); starting with defaults, old file kept as %s", path, e, bad.name)
        try:
            os.replace(path, bad)
        except OSError:
            pass
        return Settings()


class SettingsStore:
    def __init__(self, settings: Optional[Settings] = None, path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._s = (settings or Settings()).sanitised()
        self.path = Path(path) if path else None
        self._dirty = False
        self._last_save = 0.0

    def get(self) -> Settings:
        return self._s  # immutable snapshot - safe to use without the lock

    def update(self, **changes) -> Settings:
        valid = {f.name for f in fields(Settings)}
        unknown = set(changes) - valid
        if unknown:
            raise AttributeError(f"unknown setting(s): {', '.join(sorted(unknown))}")
        with self._lock:
            new = replace(self._s, **changes).sanitised()
            if new != self._s:
                self._s, self._dirty = new, True
            return self._s

    # -- persistence -------------------------------------------------------
    def save(self) -> bool:
        if self.path is None:
            return False
        with self._lock:
            data, self._dirty = asdict(self._s), False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cfg-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)  # atomic: a crash mid-write can never leave a half file
            self._last_save = time.monotonic()
            return True
        except OSError as e:
            log.warning("Could not save settings to %s: %s", self.path, e)
            return False

    def save_if_dirty(self, min_interval: float = 2.0) -> None:
        if self._dirty and time.monotonic() - self._last_save >= min_interval:
            self.save()
