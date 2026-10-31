"""The main window."""
from __future__ import annotations

import signal
import tkinter as tk
from tkinter import ttk

from ..layout import CORNER_NAMES
from ..runtime import Runtime
from .preview import PreviewCanvas
from .theme import THEME, apply_style, enable_dpi_awareness, pick_font, ui_scale
from .widgets import ColorButton, LabeledSlider, Switch

CORNER_BY_NAME = {v: k for k, v in CORNER_NAMES.items()}
DIRECTIONS = {"Clockwise": True, "Counter-clockwise": False}


class App:
    def __init__(self, rt: Runtime, fps: float):
        self.rt, self.store = rt, rt.store
        self.t = THEME
        self.root = tk.Tk()
        self.scale = ui_scale(self.root)
        self.family = pick_font(self.root)
        self.interval_ms = max(10, int(1000 / min(fps, 30)) - 4)
        self._ticks = 0
        self._closing = False
        self._last_text = self._last_warn = self._last_sub = self._last_btn = None

        root = self.root
        root.title("Nanoleaf Lightstrip")
        root.configure(bg=self.t.bg)
        root.geometry(f"{int(980 * self.scale)}x{int(700 * self.scale)}")
        root.minsize(int(780 * self.scale), int(560 * self.scale))
        apply_style(root, self.t, self.family)

        s = self.store.get()
        self._build_header(s)
        self._build_footer()           # packed from the bottom first so it never gets squeezed out
        self._build_controls(s)
        self.preview = PreviewCanvas(root, self.t, self.scale)
        self.preview.pack(fill="both", expand=True, padx=int(14 * self.scale), pady=(0, int(10 * self.scale)))

        root.protocol("WM_DELETE_WINDOW", self._request_close)
        for seq, fn in (("<Control-Right>", lambda e: self.rt.cycle_effect(1)),
                        ("<Control-Left>", lambda e: self.rt.cycle_effect(-1)),
                        ("<Control-p>", lambda e: self._set_power(not self.store.get().power))):
            root.bind(seq, fn)
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is not None:
                signal.signal(sig, lambda *_: self._request_close())

    # -- construction ---------------------------------------------------------
    def _px(self, v: float) -> int:
        return int(round(v * self.scale))

    def _label(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=kw.pop("fg", self.t.dim),
                        font=(self.family, kw.pop("size", 9), kw.pop("weight", "normal")), **kw)

    def _build_header(self, s) -> None:
        bar = tk.Frame(self.root, bg=self.t.bg)
        bar.pack(fill="x", padx=self._px(18), pady=(self._px(14), self._px(8)))
        left = tk.Frame(bar, bg=self.t.bg)
        left.pack(side="left")
        self._label(left, "Lightstrip", fg=self.t.fg, size=17, weight="bold").pack(anchor="w")
        self.sub = self._label(left, "Looking for the strip")
        self.sub.pack(anchor="w")
        right = tk.Frame(bar, bg=self.t.bg)
        right.pack(side="right")
        self._label(right, "Power", fg=self.t.fg, size=10).pack(side="left", padx=(0, self._px(10)))
        self.power = Switch(right, self.t, self.scale, s.power, self._set_power)
        self.power.pack(side="left")

    def _build_footer(self) -> None:
        foot = tk.Frame(self.root, bg=self.t.bg)
        foot.pack(side="bottom", fill="x", padx=self._px(18), pady=(0, self._px(12)))
        self.dot = tk.Label(foot, text="\u25CF", bg=self.t.bg, fg=self.t.bad, font=(self.family, 11))
        self.dot.pack(side="left")
        self.status = self._label(foot, "", fg=self.t.fg, size=10)
        self.status.pack(side="left", padx=self._px(6))
        self.button_lbl = self._label(foot, "")
        self.button_lbl.pack(side="right")
        self.warn = self._label(foot, "", fg=self.t.warn, size=10)
        self.warn.pack(side="right", padx=self._px(12))

    def _build_controls(self, s) -> None:
        wrap = tk.Frame(self.root, bg=self.t.bg)
        wrap.pack(side="bottom", fill="x", padx=self._px(14), pady=(0, self._px(10)))
        card = tk.Frame(wrap, bg=self.t.card, highlightthickness=1, highlightbackground=self.t.border)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=self.t.card)
        inner.pack(fill="x", padx=self._px(16), pady=self._px(14))
        for c in (3, 4):
            inner.columnconfigure(c, weight=1)
        pad = {"padx": (0, self._px(18)), "pady": (0, self._px(10))}

        # row 0: effect, colours, speed, brightness
        eff = tk.Frame(inner, bg=self.t.card)
        eff.grid(row=0, column=0, sticky="w", **pad)
        self._label(eff, "Effect").pack(anchor="w")
        self.effect_var = tk.StringVar(value=s.effect)
        self.effect_box = ttk.Combobox(eff, textvariable=self.effect_var, values=list(self.rt.effects),
                                       state="readonly", width=17)
        self.effect_box.pack(anchor="w", pady=(2, 0))
        self.effect_box.bind("<<ComboboxSelected>>", lambda e: self.store.update(effect=self.effect_var.get()))

        c1 = tk.Frame(inner, bg=self.t.card)
        c1.grid(row=0, column=1, sticky="w", **pad)
        self._label(c1, "Colour").pack(anchor="w")
        self.color1 = ColorButton(c1, self.t, self.scale, s.color, lambda c: self.store.update(color=c))
        self.color1.pack(anchor="w", pady=(2, 0))

        c2 = tk.Frame(inner, bg=self.t.card)
        c2.grid(row=0, column=2, sticky="w", **pad)
        self._label(c2, "Second colour").pack(anchor="w")
        self.color2 = ColorButton(c2, self.t, self.scale, s.color2, lambda c: self.store.update(color2=c))
        self.color2.pack(anchor="w", pady=(2, 0))

        self.speed = LabeledSlider(inner, self.t, self.scale, "Speed", 0.1, 4.0, s.speed,
                                   lambda v: self.store.update(speed=v), "{:.1f}x", family=self.family)
        self.speed.grid(row=0, column=3, sticky="ew", **pad)
        self.bright = LabeledSlider(inner, self.t, self.scale, "Brightness", 1, 255, s.brightness,
                                    lambda v: self.store.update(brightness=int(v)), "{:.0f}", family=self.family)
        self.bright.grid(row=0, column=4, sticky="ew", padx=(0, 0), pady=(0, self._px(10)))

        # row 1: where the strip sits
        lay = tk.Frame(inner, bg=self.t.card)
        lay.grid(row=1, column=0, columnspan=5, sticky="w")
        self._label(lay, "Strip layout:  match the ringed LED in the preview to the LED 0 end on your monitor",
                    fg=self.t.dim).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 4))
        self.start_var = tk.StringVar(value=CORNER_NAMES[s.start])
        start = ttk.Combobox(lay, textvariable=self.start_var, values=list(CORNER_NAMES.values()),
                             state="readonly", width=13)
        start.grid(row=1, column=0, padx=(0, self._px(10)))
        start.bind("<<ComboboxSelected>>", lambda e: self.store.update(start=CORNER_BY_NAME[self.start_var.get()]))
        self.dir_var = tk.StringVar(value="Clockwise" if s.clockwise else "Counter-clockwise")
        direction = ttk.Combobox(lay, textvariable=self.dir_var, values=list(DIRECTIONS), state="readonly", width=17)
        direction.grid(row=1, column=1, padx=(0, self._px(10)))
        direction.bind("<<ComboboxSelected>>",
                       lambda e: self.store.update(clockwise=DIRECTIONS[self.dir_var.get()]))
        self._label(lay, "Shift by").grid(row=1, column=2, padx=(self._px(8), 6))
        self.off_var = tk.StringVar(value=str(s.offset))
        spin = ttk.Spinbox(lay, from_=-200, to=200, width=5, textvariable=self.off_var, command=self._offset_changed)
        spin.grid(row=1, column=3)
        spin.bind("<Return>", lambda e: self._offset_changed())
        spin.bind("<FocusOut>", lambda e: self._offset_changed())
        self._label(lay, "LEDs").grid(row=1, column=4, padx=6)

    # -- actions --------------------------------------------------------------
    def _set_power(self, on: bool) -> None:
        self.store.update(power=bool(on))
        self.power.set(bool(on))

    def _offset_changed(self) -> None:
        try:
            self.store.update(offset=int(self.off_var.get()))
        except ValueError:
            self.off_var.set(str(self.store.get().offset))

    def _request_close(self) -> None:
        self._closing = True      # handled in the tick, so it is safe to call from a signal handler

    # -- live updates ---------------------------------------------------------
    def _sync_controls(self, s) -> None:
        if self.effect_var.get() != s.effect:          # e.g. the strip's own button changed it
            self.effect_var.set(s.effect)
        self.power.set(s.power)
        self.start_var.set(CORNER_NAMES[s.start])
        self.dir_var.set("Clockwise" if s.clockwise else "Counter-clockwise")
        self.color1.set_color(s.color)
        self.color2.set_color(s.color2)
        eff = self.rt.effects.get(s.effect)
        self.color1.set_enabled(bool(eff and eff.uses_color))
        self.color2.set_enabled(bool(eff and eff.uses_color2))

    def _update_status(self) -> None:
        st = self.rt.worker.status()
        text = st.text + (f"  -  {st.fps:.0f} fps" if st.ok and not st.simulated else "")
        if text != self._last_text:
            self._last_text = text
            self.status.config(text=text)
            self.dot.config(fg=self.t.warn if st.simulated else (self.t.good if st.ok else self.t.bad))
        warn = "   ".join(x for x in (st.warn, st.app_msg, self.rt.engine.error) if x)
        if warn != self._last_warn:
            self._last_warn = warn
            self.warn.config(text=warn)
        info = st.info or {}
        if st.simulated:
            sub = f"Simulated strip, {info.get('zones', 75)} zones"
        else:
            fw = info.get("firmware")
            sub = ", ".join(str(x) for x in (info.get("model"), f"firmware {fw}" if fw else None,
                                             f"{info['zones']} zones" if "zones" in info else None) if x)
            sub = sub or "Looking for the strip"
        if sub != self._last_sub:
            self._last_sub = sub
            self.sub.config(text=sub)
        btn = f"strip button: {st.last_button}" if st.last_button else ""
        if btn != self._last_btn:
            self._last_btn = btn
            self.button_lbl.config(text=btn)

    def _tick(self) -> None:
        if self._closing:
            self.root.destroy()
            return
        s = self.store.get()
        k = min(s.brightness, s.max_brightness) / 255 if s.power else 0.0
        self.preview.update_frame(self.rt.engine.preview(), k, s.layout())
        self._sync_controls(s)
        self._update_status()
        self._ticks += 1
        if self._ticks % 60 == 0:
            self.store.save_if_dirty()
        self.root.after(self.interval_ms, self._tick)

    def run(self) -> None:
        self._tick()
        self.root.mainloop()


def run_gui(rt: Runtime, fps: float) -> None:
    enable_dpi_awareness()      # must happen before the first Tk() window exists
    App(rt, fps).run()
