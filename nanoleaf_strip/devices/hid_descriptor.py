"""Tiny HID report-descriptor reader, used to work out the strip's report sizes."""
from __future__ import annotations

from typing import Dict, Tuple


def parse_hid_descriptor(desc: bytes) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Walk a report descriptor -> ({report_id: out_bytes}, {report_id: in_bytes}).

    Sizes exclude the report-id byte. report_id 0 means "unnumbered reports".
    """
    out: Dict[int, int] = {}
    inp: Dict[int, int] = {}
    g = {"size": 0, "count": 0, "rid": 0}
    stack = []
    desc = bytes(desc)
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:  # long item - never used in practice, but skip it correctly
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        nbytes = prefix & 3
        nbytes = 4 if nbytes == 3 else nbytes
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        val = int.from_bytes(desc[i + 1:i + 1 + nbytes], "little")
        i += 1 + nbytes
        if kind == 1:  # global items
            if tag == 7:
                g["size"] = val
            elif tag == 9:
                g["count"] = val
            elif tag == 8:
                g["rid"] = val
            elif tag == 10:
                stack.append(dict(g))
            elif tag == 11 and stack:
                g = stack.pop()
        elif kind == 0 and tag in (8, 9):  # main items: Input / Output
            tgt = inp if tag == 8 else out
            tgt[g["rid"]] = tgt.get(g["rid"], 0) + g["size"] * g["count"]

    def to_bytes(d: Dict[int, int]) -> Dict[int, int]:
        return {k: (v + 7) // 8 for k, v in d.items() if v > 0}

    return to_bytes(out), to_bytes(inp)
