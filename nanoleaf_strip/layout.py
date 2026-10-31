"""Where the strip physically sits around the monitor.

The strip is a closed loop of N zones. A Layout says which corner LED 0 starts at, which way
the data runs, and an optional shift in LEDs. Both the GUI preview and the screen-mirror
effect use it, so what you see in the preview is where the colours really go.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

CORNERS = ("tl", "tr", "br", "bl")
CORNER_NAMES = {"tl": "Top left", "tr": "Top right", "br": "Bottom right", "bl": "Bottom left"}

TOP, RIGHT, BOTTOM, LEFT = 0, 1, 2, 3
# Unit vector pointing from each side towards the middle of the screen.
SIDE_INWARD = ((0, 1), (-1, 0), (0, -1), (1, 0))


@dataclass(frozen=True)
class Layout:
    start: str = "tl"
    clockwise: bool = True
    offset: int = 0


def _point_at(d: float, w: float, h: float) -> Tuple[float, float, int]:
    """Point at distance d clockwise from the top-left corner, plus which side it is on."""
    if d < w:
        return (d, 0.0, TOP)
    if d < w + h:
        return (w, d - w, RIGHT)
    if d < 2 * w + h:
        return (w - (d - w - h), h, BOTTOM)
    return (0.0, h - (d - 2 * w - h), LEFT)


def zone_positions(n: int, w: float, h: float, layout: Layout = Layout()) -> List[Tuple[float, float, int]]:
    """n points spaced evenly round a w*h rectangle, in LED order -> [(x, y, side), ...]."""
    if n <= 0:
        return []
    per = 2 * (w + h)
    start_d = {"tl": 0.0, "tr": w, "br": w + h, "bl": 2 * w + h}.get(layout.start, 0.0)
    step = 1 if layout.clockwise else -1
    pts = []
    for i in range(n):
        frac = (((i + layout.offset) % n) + 0.5) / n
        d = (start_d + step * frac * per) % per
        pts.append(_point_at(d, w, h))
    return pts
