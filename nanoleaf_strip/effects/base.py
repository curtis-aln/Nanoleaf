"""Effect interface. Effects are pure functions of time -> a list of (r, g, b), one per zone."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Tuple

from ..frame import RGB, Frame
from ..layout import Layout
from ..settings import Settings


@dataclass
class RenderContext:
    n: int            # number of zones
    phase: float      # animation clock, already multiplied by the speed setting
    dt: float         # seconds since last frame, already multiplied by the speed setting
    real_dt: float    # seconds since last frame, wall-clock
    color: RGB
    color2: RGB
    layout: Layout
    settings: Settings


class Effect:
    name = "Effect"
    uses_color = False    # GUI enables the primary colour button only for effects that use it
    uses_color2 = False
    requires: Tuple[str, ...] = ()  # optional importable modules this effect needs

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        for mod in cls.requires:
            if importlib.util.find_spec(mod) is None:
                return False, f"needs '{mod}' (pip install {'pillow' if mod == 'PIL' else mod})"
        return True, ""

    def activate(self) -> None:
        """Called on the engine thread when this effect becomes the active one."""

    def deactivate(self) -> None:
        """Called when another effect replaces this one. Release threads/handles here."""

    def render(self, ctx: RenderContext) -> Frame:
        raise NotImplementedError
