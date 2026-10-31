"""Small custom widgets that give the window its look."""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, ttk
from typing import Callable, Optional, Tuple

from ..frame import clamp8, to_hex
from .theme import Theme


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


class Switch(tk.Canvas):
    """A pill toggle. Click or press Space when focused."""

    def __init__(self, master, theme: Theme, scale: float = 1.0, value: bool = False,
                 command: Optional[Callable[[bool], None]] = None):
        self.t, self.s = theme, scale
        self.w, self.h = int(46 * scale), int(26 * scale)
        super().__init__(master, width=self.w, height=self.h, bg=master["bg"], highlightthickness=0,
                         cursor="hand2", takefocus=True)
        self._value, self._cmd = value, command
        self.bind("<Button-1>", lambda e: self.toggle())
        self.bind("<space>", lambda e: self.toggle())
        self.bind("<FocusIn>", lambda e: self._draw())
        self.bind("<FocusOut>", lambda e: self._draw())
        self._draw()

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        if value != self._value:
            self._value = bool(value)
            self._draw()

    def toggle(self) -> None:
        self._value = not self._value
        self._draw()
        if self._cmd:
            self._cmd(self._value)

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.w, self.h
        col = self.t.accent if self._value else self.t.track
        self.create_oval(0, 0, h, h, fill=col, outline="")
        self.create_oval(w - h, 0, w, h, fill=col, outline="")
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=col, outline="")
        pad = 3 * self.s
        x = w - h + pad if self._value else pad
        self.create_oval(x, pad, x + h - 2 * pad, h - pad, fill="#ffffff", outline="")
        if self.focus_get() is self:
            self.create_oval(1, 1, w - 1, h - 1, outline=self.t.fg, fill="")


class ColorButton(tk.Canvas):
    """A swatch that opens the system colour picker. Dimmed and inert when the effect ignores it."""

    def __init__(self, master, theme: Theme, scale: float, color: Tuple[int, int, int],
                 on_pick: Callable[[Tuple[int, int, int]], None]):
        self.t = theme
        self.w, self.h = int(44 * scale), int(26 * scale)
        super().__init__(master, width=self.w, height=self.h, bg=master["bg"], highlightthickness=0, takefocus=True)
        self._color, self._enabled, self._on_pick = tuple(color), True, on_pick
        self.bind("<Button-1>", lambda e: self._pick())
        self.bind("<Return>", lambda e: self._pick())
        self.bind("<space>", lambda e: self._pick())
        self._draw()

    def set_color(self, color) -> None:
        if tuple(color) != self._color:
            self._color = tuple(color)
            self._draw()

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self._enabled:
            self._enabled = enabled
            self._draw()

    def _pick(self) -> None:
        if not self._enabled:
            return
        rgb, _ = colorchooser.askcolor(color=to_hex(self._color), parent=self.winfo_toplevel())
        if rgb:
            self._on_pick((clamp8(rgb[0]), clamp8(rgb[1]), clamp8(rgb[2])))

    def _draw(self) -> None:
        self.delete("all")
        fill = to_hex(self._color)
        if not self._enabled:
            fill = _mix(fill, self.t.card, 0.78)
        self.configure(cursor="hand2" if self._enabled else "arrow")
        r = self.h / 2.6
        x0, y0, x1, y1 = 1, 1, self.w - 1, self.h - 1
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        self.create_polygon(pts, smooth=True, fill=fill, outline=self.t.border if self._enabled else self.t.track)


class LabeledSlider(tk.Frame):
    def __init__(self, master, theme: Theme, scale: float, label: str, lo: float, hi: float, value: float,
                 command: Callable[[float], None], fmt: str = "{:.1f}", length: int = 170, family: str = "TkDefaultFont"):
        super().__init__(master, bg=theme.card)
        self._fmt, self._cmd = fmt, command
        tk.Label(self, text=label, bg=theme.card, fg=theme.dim, font=(family, 9)).grid(row=0, column=0, sticky="w")
        self._val = tk.Label(self, text=fmt.format(value), bg=theme.card, fg=theme.fg, font=(family, 9))
        self._val.grid(row=0, column=1, sticky="e")
        self.var = tk.DoubleVar(value=value)
        self.scale = ttk.Scale(self, from_=lo, to=hi, variable=self.var, length=int(length * scale),
                               command=self._changed)
        self.scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.columnconfigure(0, weight=1)

    def _changed(self, v: str) -> None:
        x = float(v)
        self._val.config(text=self._fmt.format(x))
        self._cmd(x)
