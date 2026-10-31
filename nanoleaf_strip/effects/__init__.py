"""Effect registry. Add a new effect by writing a class and appending it to ALL_EFFECTS."""
from __future__ import annotations

from typing import Dict, List, Tuple

from .base import Effect, RenderContext
from .classic import Breathing, Comet, Fire, Plasma, Rainbow, Solid
from .extras import Aurora, Gradient, Scanner, Twinkle
from .screen import ScreenMirror

ALL_EFFECTS = [Rainbow, Plasma, Aurora, Comet, Scanner, Fire, Twinkle, Gradient, Breathing, Solid, ScreenMirror]


def build_effects() -> Dict[str, Effect]:
    """Instances of every effect whose optional dependencies are installed, in display order."""
    return {cls.name: cls() for cls in ALL_EFFECTS if cls.available()[0]}


def unavailable_effects() -> List[Tuple[str, str]]:
    return [(cls.name, cls.available()[1]) for cls in ALL_EFFECTS if not cls.available()[0]]


__all__ = ["Effect", "RenderContext", "ALL_EFFECTS", "build_effects", "unavailable_effects"]
