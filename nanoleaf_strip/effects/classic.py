"""The six effects from the original script, ported to the new interface."""
from __future__ import annotations

import math
import random

from ..frame import Frame, hsv, scale
from .base import Effect, RenderContext


class Rainbow(Effect):
    name = "Rainbow wave"

    def render(self, ctx: RenderContext) -> Frame:
        n, ph = ctx.n, ctx.phase
        return [hsv(i / n * 1.5 - ph * 0.25) for i in range(n)]


class Plasma(Effect):
    name = "Plasma"

    def render(self, ctx: RenderContext) -> Frame:
        n, ph = ctx.n, ctx.phase
        out = []
        for i in range(n):
            x = i / n
            v = math.sin(x * 9 + ph * 1.1) + math.sin(x * 5 - ph * 0.8) + math.sin((x + ph * 0.1) * 13)
            out.append(hsv(0.5 + v / 6 + ph * 0.03, 0.9, 0.75 + 0.25 * math.sin(x * 7 + ph)))
        return out


class Comet(Effect):
    name = "Comet"
    uses_color = True

    def render(self, ctx: RenderContext) -> Frame:
        n = ctx.n
        head, tail = (ctx.phase * 14) % n, max(4.0, n * 0.18)
        out = []
        for i in range(n):
            d = (head - i) % n
            c = scale(ctx.color, math.exp(-d / tail))
            w = max(0.0, 1 - d / 2.0)
            out.append(tuple(int(v + (255 - v) * w) for v in c))
        return out


class Fire(Effect):
    name = "Fire"

    def __init__(self) -> None:
        self.heat: list = []

    @staticmethod
    def _ramp(x: float):
        # Classic "heat colour" ramp. Uses bit tests (t & 0x80 / t & 0x40) so the band edges are
        # exactly at 64 and 128 - the original used > which shifted each band by one step.
        t = int(max(0.0, min(1.0, x)) * 191)
        r = (t & 0x3F) << 2
        if t & 0x80:
            return (255, 255, r)
        if t & 0x40:
            return (255, r, 0)
        return (r, 0, 0)

    def activate(self) -> None:
        self.heat = []

    def render(self, ctx: RenderContext) -> Frame:
        n = ctx.n
        if len(self.heat) != n:
            self.heat = [0.0] * n
        f = ctx.dt * 30  # ctx.dt includes the speed slider, so Fire now respects it
        h = self.heat
        for i in range(n):
            h[i] = max(0.0, h[i] - random.uniform(0, 0.06) * f)
        h[:] = [(h[i - 1] + 2 * h[i] + h[(i + 1) % n]) / 4 for i in range(n)]
        if random.random() < min(1.0, 0.3 * f):
            j = random.randrange(n)
            h[j] = min(1.0, h[j] + random.uniform(0.5, 1.0))
        return [self._ramp(x) for x in h]


class Breathing(Effect):
    name = "Breathing"
    uses_color = True

    def render(self, ctx: RenderContext) -> Frame:
        k = 0.06 + 0.94 * ((math.sin(ctx.phase * 2.2) + 1) / 2) ** 2
        return [scale(ctx.color, k)] * ctx.n


class Solid(Effect):
    name = "Solid colour"
    uses_color = True

    def render(self, ctx: RenderContext) -> Frame:
        return [tuple(ctx.color)] * ctx.n
