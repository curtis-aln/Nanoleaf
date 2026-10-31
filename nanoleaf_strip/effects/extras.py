"""New effects."""
from __future__ import annotations

import math
import random

from ..frame import Frame, hsv, lerp, scale
from .base import Effect, RenderContext

TAU = 2 * math.pi


class Aurora(Effect):
    name = "Aurora"

    def render(self, ctx: RenderContext) -> Frame:
        n, ph = ctx.n, ctx.phase
        out = []
        for i in range(n):
            x = i / n
            # whole-number multiples of TAU keep the pattern seamless where the loop closes
            a = math.sin(TAU * x + ph * 0.5)
            b = math.sin(TAU * 2 * x - ph * 0.35)
            hue = 0.42 + 0.17 * (0.6 * a + 0.4 * b)          # green -> teal -> violet
            lift = 0.5 + 0.5 * math.sin(TAU * 3 * x + ph * 0.7 + b)
            out.append(hsv(hue, 0.85, 0.3 + 0.7 * lift ** 1.5))
        return out


class Scanner(Effect):
    name = "Scanner"
    uses_color = True

    def render(self, ctx: RenderContext) -> Frame:
        n = ctx.n
        pos = (n - 1) * (0.5 - 0.5 * math.cos(ctx.phase * 2.0))   # smooth ping-pong, slows at the ends
        width = max(2.0, n * 0.05)
        return [scale(ctx.color, math.exp(-((i - pos) ** 2) / (2 * width * width))) for i in range(n)]


class Twinkle(Effect):
    name = "Twinkle"
    uses_color = True

    def __init__(self) -> None:
        self.level: list = []

    def activate(self) -> None:
        self.level = []

    def render(self, ctx: RenderContext) -> Frame:
        n = ctx.n
        if len(self.level) != n:
            self.level = [0.0] * n
        lv = self.level
        decay = math.exp(-ctx.dt * 2.5)
        for i in range(n):
            lv[i] *= decay
        expected = ctx.dt * n * 0.8                      # sparkles born this frame
        born = int(expected) + (1 if random.random() < expected - int(expected) else 0)
        for _ in range(born):
            lv[random.randrange(n)] = 1.0
        base = scale(ctx.color, 0.10)
        out = []
        for v in lv:
            c = lerp(base, ctx.color, v)
            out.append(lerp(c, (255, 255, 255), max(0.0, (v - 0.7) / 0.3) * 0.8))
        return out


class Gradient(Effect):
    name = "Gradient"
    uses_color = True
    uses_color2 = True

    def render(self, ctx: RenderContext) -> Frame:
        n = ctx.n
        return [lerp(ctx.color, ctx.color2, 0.5 + 0.5 * math.sin(TAU * i / n - ctx.phase * 0.8)) for i in range(n)]
