"""Pure-Pillow renderer for the live preview (no Tk needed, so it is easy to test).

Draws a monitor with the strip around it. Each LED gets a crisp core plus two additive glow
layers, so bright colours bloom into the backdrop the way the real strip lights a wall.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..frame import Frame
from ..layout import Layout, zone_positions
from .theme import THEME

_BOX = getattr(Image, "Resampling", Image).BILINEAR
OFF = (40, 43, 62)


def _hex(c: str) -> Tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow < 10.1
        return ImageFont.load_default()


class PreviewRenderer:
    def __init__(self, width: int, height: int, scale: float = 1.0):
        self.w, self.h, self.s = max(240, int(width)), max(180, int(height)), scale
        self._pts_key = None
        self._sprites = {}
        self._pts: List[Tuple[float, float]] = []
        self._lut_wide = [int(i * 0.9) for i in range(256)] * 3
        self._lut_mid = [int(i * 0.8) for i in range(256)] * 3
        self._font = _font(max(9, int(11 * scale)))
        self._build_base()

    # -- static scene (built once per window size) ---------------------------
    def _build_base(self) -> None:
        w, h, s = self.w, self.h, self.s
        top, bot = _hex(THEME.bg_top), _hex(THEME.bg)
        grad = Image.linear_gradient("L").resize((w, h))
        base = ImageOps.colorize(grad.transpose(Image.FLIP_TOP_BOTTOM), black=bot, white=top)
        vign = Image.radial_gradient("L").resize((w, h)).point(lambda v: int(v * 0.55))
        base = Image.composite(Image.new("RGB", (w, h), (6, 7, 12)), base, vign)

        self.bar_h = int(h * 0.17)
        stage_h = h - self.bar_h
        mw = min(w * 0.50, stage_h * 0.60 * 16 / 9)
        mh = mw * 9 / 16
        cx, cy = w / 2, stage_h * 0.50
        self.mon = (cx - mw / 2, cy - mh / 2, cx + mw / 2, cy + mh / 2)
        m = max(14 * s, mh * 0.11)
        self.led_rect = (self.mon[0] - m, self.mon[1] - m, self.mon[2] + m, self.mon[3] + m)

        d = ImageDraw.Draw(base)
        x0, y0, x1, y1 = (int(v) for v in self.mon)
        radius = int(6 * s)
        # screen glass: a faint top-to-bottom sheen inside a rounded outline
        sheen = ImageOps.colorize(Image.linear_gradient("L").resize((x1 - x0, y1 - y0)).transpose(Image.FLIP_TOP_BOTTOM),
                                  black=(5, 6, 10), white=(15, 17, 27))
        mask = Image.new("L", sheen.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, sheen.width - 1, sheen.height - 1), radius=radius, fill=255)
        base.paste(sheen, (x0, y0), mask)
        d.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=(48, 52, 76), width=max(1, int(2 * s)))
        # stand
        sx = int(mw * 0.07)
        d.polygon([(cx - sx, y1), (cx + sx, y1), (cx + sx * 2.2, y1 + 12 * s), (cx - sx * 2.2, y1 + 12 * s)], fill=(20, 22, 33))
        self.base = base

    def _sprite(self, diameter: float, ring_width: float = 0.0) -> Image.Image:
        """Anti-aliased disc (or ring) used as a paste mask; cached because sizes rarely change."""
        d = max(2, int(round(diameter)))
        key = (d, round(ring_width, 1))
        got = self._sprites.get(key)
        if got is None:
            ss = 6
            big = Image.new("L", (d * ss, d * ss), 0)
            bd = ImageDraw.Draw(big)
            if ring_width:
                bd.ellipse((0, 0, d * ss - 1, d * ss - 1), outline=255, width=max(1, int(ring_width * ss)))
            else:
                bd.ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
            got = self._sprites[key] = big.resize((d, d), getattr(Image, "Resampling", Image).LANCZOS)
        return got

    def _points(self, n: int, layout: Layout):
        key = (n, layout)
        if key != self._pts_key:
            x0, y0, x1, y1 = self.led_rect
            self._pts = [(x0 + x, y0 + y) for x, y, _ in zone_positions(n, x1 - x0, y1 - y0, layout)]
            self._pts_key = key
        return self._pts

    # -- per frame -------------------------------------------------------------
    def render(self, frame: Frame, k: float, layout: Layout = Layout()) -> Image.Image:
        n, s = len(frame), self.s
        pts = self._points(n, layout)
        cols = [(int(r * k), int(g * k), int(b * k)) for r, g, b in frame]
        lx0, ly0, lx1, ly1 = self.led_rect
        spacing = 2 * ((lx1 - lx0) + (ly1 - ly0)) / max(1, n)
        r = max(2.5 * s, min(6.0 * s, spacing * 0.28))

        # glow: drawn small, blurred, scaled up, added on top
        hw, hh = self.w // 2, self.h // 2
        glow = Image.new("RGB", (hw, hh), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gr = r * 1.7 / 2
        for (x, y), c in zip(pts, cols):
            if c[0] + c[1] + c[2] > 12:
                gd.ellipse((x / 2 - gr, y / 2 - gr, x / 2 + gr, y / 2 + gr), fill=c)
        wide = glow.filter(ImageFilter.GaussianBlur(11 * s / 2 * 1.6)).resize((self.w, self.h), _BOX)
        mid = glow.filter(ImageFilter.GaussianBlur(4 * s)).resize((self.w, self.h), _BOX)
        img = ImageChops.add(self.base, wide.point(self._lut_wide))
        img = ImageChops.add(img, mid.point(self._lut_mid))

        dot = self._sprite(2 * r)
        core = self._sprite(r * 0.95)
        for (x, y), c in zip(pts, cols):
            fill = (max(c[0], OFF[0]), max(c[1], OFF[1]), max(c[2], OFF[2]))
            img.paste(fill, (int(round(x - dot.width / 2)), int(round(y - dot.height / 2))), dot)
            if c[0] + c[1] + c[2] > 120:     # hot core
                hot = tuple(int(v + (255 - v) * 0.45) for v in c)
                img.paste(hot, (int(round(x - core.width / 2)), int(round(y - core.height / 2))), core)
        if pts:                               # ring marks LED 0 so you can match the preview to your wiring
            x, y = pts[0]
            ring = self._sprite(2 * (r + 3.5 * s), ring_width=max(1.0, s))
            img.paste((235, 238, 250), (int(round(x - ring.width / 2)), int(round(y - ring.height / 2))), ring)

        d = ImageDraw.Draw(img)
        self._draw_data_bar(d, cols)
        return img

    def _draw_data_bar(self, d: ImageDraw.ImageDraw, cols: Sequence[Tuple[int, int, int]]) -> None:
        n, s = len(cols), self.s
        pad = int(28 * s)
        y0 = self.h - self.bar_h + int(self.bar_h * 0.18)
        y1 = y0 + int(self.bar_h * 0.34)
        bw = (self.w - 2 * pad) / max(1, n)
        for i, c in enumerate(cols):
            fill = (max(c[0], OFF[0]), max(c[1], OFF[1]), max(c[2], OFF[2]))
            d.rectangle((pad + i * bw, y0, pad + (i + 1) * bw - 1, y1), fill=fill)
        dim = _hex(THEME.dim)
        ty = y1 + int(7 * s)
        d.text((pad, ty), "LED 0", fill=dim, font=self._font)
        right = f"LED {n - 1}"
        d.text((self.w - pad - d.textlength(right, font=self._font), ty), right, fill=dim, font=self._font)
        mid = "order sent over USB"
        d.text(((self.w - d.textlength(mid, font=self._font)) / 2, ty), mid, fill=(88, 93, 120), font=self._font)
