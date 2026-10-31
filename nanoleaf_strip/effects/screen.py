"""Screen mirror: light the strip with the colours at the edges of the monitor.

Needs Pillow (and optionally `mss`, which is faster than Pillow's ImageGrab on Windows/Linux).
Capture runs in its own thread so a slow grab never stalls the animation clock.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, List, Optional, Tuple

from ..frame import Frame, black
from ..layout import SIDE_INWARD, Layout, zone_positions
from .base import Effect, RenderContext

log = logging.getLogger(__name__)

GRID_COLS, GRID_ROWS = 96, 54

# A "source" returns (small RGB PIL image of GRID_COLS x GRID_ROWS, (screen_w, screen_h)).
Grab = Callable[[int, int], Tuple[object, Tuple[int, int]]]


def default_source_factory() -> Tuple[Grab, Callable[[], None]]:
    from PIL import Image
    box = getattr(getattr(Image, "Resampling", Image), "BOX")
    try:
        import mss  # type: ignore
    except ImportError:
        mss = None
    if mss is not None:
        sct = mss.mss()
        mon = sct.monitors[1]  # primary monitor

        def grab(cols: int, rows: int):
            shot = sct.grab(mon)
            img = Image.frombuffer("RGB", shot.size, shot.bgra, "raw", "BGRX", 0, 1)
            return img.resize((cols, rows), box), tuple(shot.size)

        return grab, sct.close

    from PIL import ImageGrab

    def grab(cols: int, rows: int):
        img = ImageGrab.grab().convert("RGB")
        return img.resize((cols, rows), box), img.size

    return grab, lambda: None


class ScreenGrabber(threading.Thread):
    def __init__(self, factory=default_source_factory, fps: float = 30.0):
        super().__init__(name="screen-grab", daemon=True)
        self._factory, self._interval = factory, 1.0 / fps
        self._halt = threading.Event()
        self._latest: Optional[Tuple[object, Tuple[int, int]]] = None
        self.error = ""

    def latest(self):
        return self._latest

    def stop(self) -> None:
        self._halt.set()
        if self.is_alive():
            self.join(timeout=1.5)

    def run(self) -> None:
        try:
            grab, close = self._factory()   # created here: mss handles are per-thread
        except Exception as e:  # noqa: BLE001
            self.error = f"screen capture unavailable: {e}"
            return
        try:
            while not self._halt.is_set():
                t = time.monotonic()
                try:
                    self._latest = grab(GRID_COLS, GRID_ROWS)
                    self.error = ""
                except Exception as e:  # noqa: BLE001 - e.g. secure desktop / screen locked
                    self.error = f"screen capture failed: {e}"
                    self._halt.wait(1.0)
                self._halt.wait(max(0.0, self._interval - (time.monotonic() - t)))
        finally:
            try:
                close()
            except Exception:  # noqa: BLE001
                pass


class ScreenMirror(Effect):
    name = "Screen mirror"
    requires = ("PIL",)

    def __init__(self, source_factory=default_source_factory):
        self._factory = source_factory
        self._grabber: Optional[ScreenGrabber] = None
        self._smooth: List[List[float]] = []
        self._plan_key = None
        self._plan: List[List[Tuple[int, int]]] = []

    def activate(self) -> None:
        self._smooth = []
        self._grabber = ScreenGrabber(self._factory)
        self._grabber.start()

    def deactivate(self) -> None:
        if self._grabber:
            self._grabber.stop()
            self._grabber = None

    def _plan_for(self, n: int, layout: Layout, size: Tuple[int, int], depth: float):
        key = (n, layout, size, round(depth, 3))
        if key == self._plan_key:
            return self._plan
        sw, sh = size
        plan = []
        for x, y, side in zone_positions(n, float(sw), float(sh), layout):
            dx, dy = SIDE_INWARD[side]
            u, v = x / sw * GRID_COLS, y / sh * GRID_ROWS
            steps = max(1, round(depth * (GRID_COLS if dx else GRID_ROWS)))
            cells = set()
            for s in range(steps):
                for t in (-1, 0, 1):   # a 3-cell-wide strip along the edge
                    cx = u + dx * (s + 0.5) + (t if dy else 0)
                    cy = v + dy * (s + 0.5) + (t if dx else 0)
                    cells.add((min(GRID_COLS - 1, max(0, int(cx))), min(GRID_ROWS - 1, max(0, int(cy)))))
            plan.append(sorted(cells))
        self._plan_key, self._plan = key, plan
        return plan

    def render(self, ctx: RenderContext) -> Frame:
        g = self._grabber
        got = g.latest() if g else None
        if got is None:
            if g and g.error:
                raise RuntimeError(g.error)
            return black(ctx.n)                     # still waiting for the first capture
        img, size = got
        s = ctx.settings
        plan = self._plan_for(ctx.n, ctx.layout, size, s.screen_depth)
        px = img.load()
        if len(self._smooth) != ctx.n:
            self._smooth = [None] * ctx.n          # type: ignore[list-item]
        alpha = 1.0 - math.exp(-ctx.real_dt * s.screen_response)
        sat = s.screen_saturation
        out: Frame = []
        for i, cells in enumerate(plan):
            r = g_ = b = 0
            for cx, cy in cells:
                p = px[cx, cy]
                r, g_, b = r + p[0], g_ + p[1], b + p[2]
            k = 1.0 / len(cells)
            r, g_, b = r * k, g_ * k, b * k
            lum = 0.299 * r + 0.587 * g_ + 0.114 * b
            tgt = [lum + (c - lum) * sat for c in (r, g_, b)]
            cur = self._smooth[i]
            cur = tgt if cur is None else [c + (t - c) * alpha for c, t in zip(cur, tgt)]
            self._smooth[i] = cur
            out.append((int(max(0, min(255, cur[0]))), int(max(0, min(255, cur[1]))), int(max(0, min(255, cur[2])))))
        return out
