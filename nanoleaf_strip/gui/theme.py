"""Colours, fonts, DPI handling and ttk styling."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from ..constants import IS_WINDOWS


@dataclass(frozen=True)
class Theme:
    bg: str = "#0c0e16"          # window backdrop
    bg_top: str = "#171a2b"      # top of the backdrop gradient
    card: str = "#161929"        # control panel
    field: str = "#0f111b"       # inputs
    border: str = "#2b3048"
    track: str = "#2b3048"
    fg: str = "#eceef7"
    dim: str = "#8c92ae"
    accent: str = "#7f8dff"
    good: str = "#3ddc97"
    warn: str = "#f5b14a"
    bad: str = "#ff6b6b"


THEME = Theme()

FONT_CHOICES = ("Inter", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue",
                "Cantarell", "Noto Sans", "DejaVu Sans")


def enable_dpi_awareness() -> None:
    """Without this, Windows bitmap-scales the whole window and the preview looks blurry. Call before Tk()."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def ui_scale(root) -> float:
    try:
        return max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:  # noqa: BLE001
        return 1.0


def pick_font(root) -> str:
    have = set(tkfont.families(root))
    for name in FONT_CHOICES:
        if name in have:
            return name
    return "TkDefaultFont"


def apply_style(root, theme: Theme, family: str) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=theme.card, foreground=theme.fg, font=(family, 10), borderwidth=0)
    st.configure("TCombobox", fieldbackground=theme.field, background=theme.field, foreground=theme.fg,
                 arrowcolor=theme.dim, bordercolor=theme.border, lightcolor=theme.border,
                 darkcolor=theme.border, selectbackground=theme.field, selectforeground=theme.fg, padding=5)
    st.map("TCombobox",
           fieldbackground=[("readonly", theme.field)], foreground=[("readonly", theme.fg)],
           selectbackground=[("readonly", theme.field)], selectforeground=[("readonly", theme.fg)],
           bordercolor=[("focus", theme.accent)], arrowcolor=[("active", theme.fg)])
    st.configure("TSpinbox", fieldbackground=theme.field, background=theme.field, foreground=theme.fg,
                 arrowcolor=theme.dim, bordercolor=theme.border, lightcolor=theme.border,
                 darkcolor=theme.border, padding=4)
    st.map("TSpinbox", bordercolor=[("focus", theme.accent)])
    st.configure("Horizontal.TScale", background=theme.accent, troughcolor=theme.track,
                 bordercolor=theme.card, lightcolor=theme.accent, darkcolor=theme.accent)
    st.map("Horizontal.TScale", background=[("active", "#a0abff")])
    root.option_add("*TCombobox*Listbox.background", theme.card)
    root.option_add("*TCombobox*Listbox.foreground", theme.fg)
    root.option_add("*TCombobox*Listbox.selectBackground", theme.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", "#0c0e16")
    root.option_add("*TCombobox*Listbox.font", (family, 10))
