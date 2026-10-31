"""Colour helpers and the last-line-of-defence processing every outgoing frame goes through."""
from __future__ import annotations

import colorsys
from typing import List, Sequence, Tuple

RGB = Tuple[int, int, int]
Frame = List[RGB]

BLACK: RGB = (0, 0, 0)


def clamp8(v: float) -> int:
    return 0 if v <= 0 else 255 if v >= 255 else int(v)


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.0, s)), min(1.0, max(0.0, v)))
    return (int(r * 255), int(g * 255), int(b * 255))


def scale(c: Sequence[float], k: float) -> RGB:
    return (clamp8(c[0] * k), clamp8(c[1] * k), clamp8(c[2] * k))


def lerp(a: Sequence[float], b: Sequence[float], t: float) -> RGB:
    t = min(1.0, max(0.0, t))
    return (clamp8(a[0] + (b[0] - a[0]) * t),
            clamp8(a[1] + (b[1] - a[1]) * t),
            clamp8(a[2] + (b[2] - a[2]) * t))


def black(n: int) -> Frame:
    return [BLACK] * n


def sanitize(frame: Sequence[Sequence[float]], n: int) -> Frame:
    """Return exactly n clean (r, g, b) int tuples in 0..255.

    Wrong-length frames (e.g. after a reconnect to a different strip) are resampled
    rather than rejected; garbage values are clamped; an empty frame becomes black.
    """
    if n <= 0:
        return []
    if not frame:
        return black(n)
    m = len(frame)
    src = frame if m == n else [frame[min(m - 1, i * m // n)] for i in range(n)]
    return [(clamp8(p[0]), clamp8(p[1]), clamp8(p[2])) for p in src]


def limit_power(frame: Frame, limit: float) -> Frame:
    """Scale the frame down so its total channel sum is at most `limit` of the all-white maximum.

    Protects USB power budgets: 1.0 disables the limiter, 0.5 allows half of full-white draw.
    """
    if limit >= 1.0 or not frame:
        return frame
    total = sum(r + g + b for r, g, b in frame)
    cap = len(frame) * 765 * max(0.02, limit)
    if total <= cap:
        return frame
    k = cap / total
    return [(int(r * k), int(g * k), int(b * k)) for r, g, b in frame]


def crossfade(a: Frame, b: Frame, t: float) -> Frame:
    """Blend frame a into frame b (same length); t=0 gives a, t=1 gives b."""
    return [lerp(p, q, t) for p, q in zip(a, b)]


def parse_color(text: str) -> RGB:
    """Accept '#rrggbb', 'rrggbb', '#rgb' or 'r,g,b'."""
    t = text.strip()
    if "," in t:
        parts = [int(x) for x in t.split(",")]
        if len(parts) != 3:
            raise ValueError("expected r,g,b")
        return (clamp8(parts[0]), clamp8(parts[1]), clamp8(parts[2]))
    t = t.lstrip("#")
    if len(t) == 3:
        t = "".join(ch * 2 for ch in t)
    if len(t) != 6:
        raise ValueError("expected #rrggbb")
    return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))


def to_hex(c: Sequence[float]) -> str:
    return "#%02x%02x%02x" % (clamp8(c[0]), clamp8(c[1]), clamp8(c[2]))
