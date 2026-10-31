"""The animation clock. Runs on its own thread, so the GUI (or a modal dialog, or no GUI at all)
can never stall the strip.

Fail-safe behaviour: an effect that raises is logged and shown as black instead of killing the
loop; frames are always sanitised to the strip's length; a crossfade softens effect switches.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

from .effects import Effect, RenderContext
from .effects.classic import Solid
from .frame import Frame, black, crossfade, sanitize
from .settings import SettingsStore
from .worker import Worker

log = logging.getLogger(__name__)


class Engine(threading.Thread):
    def __init__(self, store: SettingsStore, worker: Worker, effects: Dict[str, Effect], fps: float):
        super().__init__(name="strip-engine", daemon=True)
        self.store, self.worker, self.effects = store, worker, effects
        self.interval = 1.0 / fps
        self._fallback = effects.get(Solid.name) or next(iter(effects.values()))
        self._halt = threading.Event()
        self._preview: Frame = black(worker.length)
        self.error = ""
        self._logged = ""

    def preview(self) -> Frame:
        """Latest rendered frame (an immutable-by-convention list, safe to read from any thread)."""
        return self._preview

    def stop(self) -> None:
        self._halt.set()
        if self.ident is not None:
            self.join(timeout=2.0)

    def _safe(self, effect: Effect, method: str) -> None:
        try:
            getattr(effect, method)()
        except Exception as e:  # noqa: BLE001
            self._report(effect, e)

    def _report(self, effect: Effect, exc: Exception) -> None:
        self.error = f"{effect.name}: {exc}"
        if self.error != self._logged:       # one log line per distinct failure, not 30 a second
            self._logged = self.error
            log.error("effect failed: %s", self.error, exc_info=exc)

    def run(self) -> None:
        current: Optional[Effect] = None
        last, phase = time.monotonic(), 0.0
        fade_from: Optional[Frame] = None
        fade_left = fade_total = 0.0
        try:
            while not self._halt.is_set():
                tick = time.monotonic()
                real_dt, last = min(tick - last, 0.1), tick
                s = self.store.get()
                n = self.worker.length
                eff = self.effects.get(s.effect) or self._fallback

                if eff is not current:
                    if current is not None:
                        self._safe(current, "deactivate")
                        if s.fade > 0:
                            fade_from, fade_left, fade_total = self._preview, s.fade, s.fade
                    self.error = ""
                    self._safe(eff, "activate")
                    current = eff

                phase += real_dt * s.speed
                ctx = RenderContext(n, phase, real_dt * s.speed, real_dt, s.color, s.color2, s.layout(), s)
                try:
                    frame = sanitize(eff.render(ctx), n)
                    self.error = ""
                except Exception as e:  # noqa: BLE001
                    self._report(eff, e)
                    frame = black(n)

                if fade_from is not None and fade_left > 0:
                    k = 1.0 - fade_left / fade_total
                    frame = crossfade(sanitize(fade_from, n), frame, k * k * (3 - 2 * k))  # smoothstep
                    fade_left -= real_dt
                else:
                    fade_from = None

                self._preview = frame
                self.worker.submit(frame)
                self._halt.wait(max(0.0, self.interval - (time.monotonic() - tick)))
        finally:
            if current is not None:
                self._safe(current, "deactivate")
