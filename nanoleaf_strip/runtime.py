"""Wires the pieces together: store -> engine -> worker -> device."""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from .devices.base import BaseDevice
from .effects import Effect, build_effects
from .engine import Engine
from .procs import AppWatcher
from .settings import SettingsStore
from .worker import Worker

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, store: SettingsStore, device: BaseDevice, fps: float,
                 effects: Optional[Dict[str, Effect]] = None):
        self.store, self.device = store, device
        self.effects = effects if effects is not None else build_effects()
        self.watcher = None if device.simulated else AppWatcher()
        self.worker = Worker(device, store, fps, self.watcher)
        self.engine = Engine(store, self.worker, self.effects, fps)
        self.worker.on_button = self._on_button
        self._last_button = 0.0

    def start(self) -> None:
        if self.watcher:
            self.watcher.start()
        self.worker.start()
        self.engine.start()

    def stop(self) -> None:
        """Engine first (no more frames), then the worker, which blanks the strip on its way out."""
        self.engine.stop()
        self.worker.stop(self.store.get().on_exit)
        if self.watcher:
            self.watcher.stop()
        self.store.save()

    def cycle_effect(self, step: int = 1) -> str:
        names = list(self.effects)
        cur = self.store.get().effect
        idx = (names.index(cur) + step) % len(names) if cur in names else 0
        self.store.update(effect=names[idx])
        return names[idx]

    def _on_button(self, body: bytes) -> None:
        # Payload meaning is not documented, so any event counts as a press; debounce press/release pairs.
        if self.store.get().button_action != "cycle":
            return
        now = time.monotonic()
        if now - self._last_button > 0.6:
            self._last_button = now
            log.info("button event %s -> next effect: %s", body.hex(), self.cycle_effect())
