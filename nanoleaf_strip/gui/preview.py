"""Tk canvas that shows the live preview. Uses the Pillow renderer when available and a simple
dot-and-bar drawing otherwise."""
from __future__ import annotations

import tkinter as tk
from typing import List

from ..frame import Frame, to_hex
from ..layout import Layout, zone_positions
from .theme import Theme

try:
    from PIL import ImageTk
    from .render import PreviewRenderer
    HAVE_PIL = True
except ImportError:      # Pillow missing, or built without Tk support
    HAVE_PIL = False


class PreviewCanvas(tk.Canvas):
    def __init__(self, master, theme: Theme, scale: float = 1.0):
        super().__init__(master, bg=theme.bg, highlightthickness=0)
        self.t, self.s = theme, scale
        self._size = (0, 0)
        self._renderer = None
        self._photo = None
        self._fallback_key = None
        self._dots: List[int] = []
        self._bars: List[int] = []
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, e) -> None:
        if (e.width, e.height) != self._size and e.width > 80 and e.height > 80:
            self._size = (e.width, e.height)
            self._renderer = None
            self._photo = None
            self.delete("all")
            self._fallback_key = None

    def update_frame(self, frame: Frame, k: float, layout: Layout) -> None:
        w, h = self._size
        if w < 80 or not frame:
            return
        if HAVE_PIL:
            if self._renderer is None:
                self._renderer = PreviewRenderer(w, h, self.s)
            img = self._renderer.render(frame, k, layout)
            if self._photo is None:
                self._photo = ImageTk.PhotoImage(img)
                self.create_image(0, 0, anchor="nw", image=self._photo)
            else:
                self._photo.paste(img)
        else:
            self._draw_plain(frame, k, layout, w, h)

    def _draw_plain(self, frame: Frame, k: float, layout: Layout, w: int, h: int) -> None:
        n = len(frame)
        key = (n, layout, w, h)
        if key != self._fallback_key:
            self.delete("all")
            mw = min(w * 0.45, (h * 0.6) * 16 / 9)
            mh = mw * 9 / 16
            x0, y0 = (w - mw) / 2, (h * 0.8 - mh) / 2
            self.create_rectangle(x0, y0, x0 + mw, y0 + mh, fill="#05060a", outline=self.t.border, width=2)
            m = 20 * self.s
            pts = zone_positions(n, mw + 2 * m, mh + 2 * m, layout)
            self._dots = [self.create_oval(x0 - m + x - 5, y0 - m + y - 5, x0 - m + x + 5, y0 - m + y + 5,
                                           fill=self.t.track, outline="") for x, y, _ in pts]
            bw = (w - 60) / n
            by = h * 0.88
            self._bars = [self.create_rectangle(30 + i * bw, by, 30 + (i + 1) * bw - 1, by + 24,
                                                fill=self.t.track, outline="") for i in range(n)]
            self._fallback_key = key
        for ids, (r, g, b) in zip(zip(self._dots, self._bars), frame):
            c = to_hex((r * k, g * k, b * k))
            self.itemconfig(ids[0], fill=c)
            self.itemconfig(ids[1], fill=c)
