"""Real strip over USB HID.

Protocol: Nanoleaf "USB Lightstrip Communication Protocol" (VID 0x37FA, PID 0x8202).
Messages are TLV: [type:1][length:2 big-endian][payload]; reply type = 0x80 + type.
Only ever touch an instance from one thread (the worker).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..constants import (CMD_GET_BRI, CMD_GET_FW, CMD_GET_LEN, CMD_GET_MODEL, CMD_GET_POWER,
                         CMD_SET_BRI, CMD_SET_POWER, CMD_SET_RGB, EVT_BUTTON, IS_WINDOWS, PID, VID)
from ..errors import DeviceError
from .base import BaseDevice
from .hid_descriptor import parse_hid_descriptor

log = logging.getLogger(__name__)


def load_hid():
    """Import hidapi. Returns (module, problem) where problem is '' when the module is usable.

    There are two unrelated PyPI packages that both import as `hid`; only `hidapi` works here.
    """
    try:
        import hid  # type: ignore
    except ImportError:
        return None, "hidapi not installed (pip install hidapi)"
    if not hasattr(hid, "device") or not hasattr(hid, "enumerate"):
        return None, "the wrong 'hid' package is installed - run: pip uninstall hid && pip install hidapi"
    return hid, ""


def _get_descriptor(h) -> bytes:
    try:
        return bytes(h.get_report_descriptor())
    except Exception:  # noqa: BLE001 - older hidapi builds lack this call
        return b""


class StripDevice(BaseDevice):
    simulated = False

    def __init__(self, report_id: Optional[int] = None, report_size: Optional[int] = None,
                 hid_module=None):
        super().__init__()
        if hid_module is not None:
            self._hid, self._hid_problem = hid_module, ""
        else:
            self._hid, self._hid_problem = load_hid()
        self.force: Optional[Tuple[int, int]] = None
        if report_id is not None or report_size is not None:
            self.force = (report_id or 0, report_size or 64)
        self.h = None
        self.rid, self.size = 0, 64
        self.chunks = 1
        self.detail = ""

    # -- connection ---------------------------------------------------------
    def _detect_size_windows(self, h, rid: int) -> Optional[int]:
        """Windows hidapi zero-pads writes shorter than the device's output report and fails longer
        ones, so the largest write length that succeeds IS the report length. Probes with harmless
        GET_LEN messages. Returns data bytes per report (excluding the id byte) or None."""
        hdr = bytes([CMD_GET_LEN, 0, 0])

        def ok(d: int) -> bool:
            try:
                return h.write(bytes([rid]) + hdr.ljust(d, b"\0")) >= 0
            except Exception:  # noqa: BLE001
                return False

        size = None
        if ok(3) and not ok(4096):
            lo, hi = 3, 4096
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (mid, hi) if ok(mid) else (lo, mid)
            size = lo
        for _ in range(64):  # swallow the replies those probe writes provoked
            if not h.read(1025, 30):
                break
        return size

    def _candidates(self, h) -> List[Tuple[int, int]]:
        cands: List[Tuple[int, int]] = []
        if self.force:
            cands.append(self.force)
        desc = _get_descriptor(h)
        if desc:
            out, _ = parse_hid_descriptor(desc)
            cands += sorted(out.items(), key=lambda kv: -kv[1])
        if IS_WINDOWS:
            for rid in (0, 1):
                size = self._detect_size_windows(h, rid)
                if size:
                    cands.append((rid, size))
                    break
        cands += [(0, 64), (0, 32), (0, 63), (0, 16), (1, 63), (1, 64)]
        seen, uniq = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        return uniq

    def connect(self) -> Tuple[bool, str]:
        if self._hid is None:
            return False, self._hid_problem
        try:
            infos = self._hid.enumerate(VID, PID)
        except Exception as e:  # noqa: BLE001
            return False, f"USB enumeration failed: {e}"
        if not infos:
            return False, "Strip not found on USB (37FA:8202) - replug it?"
        last = "no HID interface answered the length query"
        for info in infos:
            h = self._hid.device()
            try:
                h.open_path(info["path"])
            except Exception as e:  # noqa: BLE001
                last = f"could not open device ({e}) - quit Nanoleaf Desktop?"
                continue
            self.h = h
            passing = []
            for rid, size in self._candidates(h):
                self.rid, self.size = rid, size
                try:
                    pl = self._txrx(CMD_GET_LEN, timeout=300)
                except DeviceError:
                    continue
                if len(pl) == 2 and pl[0] == 0:
                    passing.append((rid, size, pl[1]))
                    if not IS_WINDOWS or (rid, size) == self.force:
                        break
            if passing:
                # On Windows short writes get zero-padded, so several sizes "work"; the real one is the largest.
                forced = [p for p in passing if (p[0], p[1]) == self.force]
                rid, size, zones = forced[0] if forced else max(passing, key=lambda p: p[1])
                self.rid, self.size, self.length = rid, size, max(1, zones)
                self.chunks = -(-(3 + 3 * self.length) // size)
                self.connected = True
                self.detail = f"report id {rid}, {size} B, {self.chunks} report(s)/frame"
                return True, f"Connected - {self.length} zones ({self.detail})"
            h.close()
            self.h = None
        return False, last

    def close(self) -> None:
        self.connected = False
        if self.h is not None:
            try:
                self.h.close()
            except Exception:  # noqa: BLE001
                pass
            self.h = None

    # -- transport ----------------------------------------------------------
    def _write_msg(self, msg: bytes) -> None:
        for i in range(0, len(msg), self.size):
            chunk = msg[i:i + self.size].ljust(self.size, b"\0")
            if self.h.write(bytes([self.rid]) + chunk) < 0:
                raise DeviceError("USB write failed")

    def _txrx(self, mtype: int, payload: bytes = b"", timeout: int = 250) -> bytes:
        if self.h is None:
            raise DeviceError("device is closed")
        msg = bytes([mtype, len(payload) >> 8, len(payload) & 0xFF]) + payload
        try:
            self._write_msg(msg)
            deadline = time.monotonic() + timeout / 1000
            while True:
                left = int((deadline - time.monotonic()) * 1000)
                if left <= 0:
                    raise DeviceError(f"no reply to command 0x{mtype:02X}")
                data = bytes(self.h.read(1025, left))
                if self.rid and data[:1] == bytes([self.rid]):
                    data = data[1:]
                if len(data) < 3:
                    continue
                rtype, rlen = data[0], (data[1] << 8) | data[2]
                body = data[3:3 + rlen]
                if rtype == EVT_BUTTON:
                    self._emit_button(body)
                    continue
                if rtype == 0x80 + mtype:
                    return body
        except (OSError, ValueError) as e:
            raise DeviceError(str(e)) from e

    def _emit_button(self, body: bytes) -> None:
        if self.on_button:
            try:
                self.on_button(body)
            except Exception:  # noqa: BLE001 - a bad callback must never break streaming
                log.exception("button callback failed")

    # -- commands -----------------------------------------------------------
    def set_pixels(self, rgb: Sequence[Sequence[int]]) -> int:
        payload = bytes(max(0, min(255, int(v))) for px in rgb for v in px)
        pl = self._txrx(CMD_SET_RGB, payload, timeout=150)
        return pl[0] if pl else 1  # 0 = success

    def set_power(self, on: bool) -> None:
        self._txrx(CMD_SET_POWER, bytes([1 if on else 0]))

    def set_brightness(self, value: int) -> None:
        self._txrx(CMD_SET_BRI, bytes([max(0, min(255, int(value)))]))

    def info(self) -> Dict[str, object]:
        d: Dict[str, object] = {}
        m = self._txrx(CMD_GET_MODEL)
        if len(m) >= 7 and m[0] == 0:
            d["model"] = m[1:7].decode("ascii", "replace")
        f = self._txrx(CMD_GET_FW)
        if len(f) >= 2 and f[0] == 0:
            d["firmware"] = f"{f[1] >> 4}.{f[1] & 0xF}"
        b = self._txrx(CMD_GET_BRI)
        if len(b) >= 2 and b[0] == 0:
            d["brightness"] = b[1]
        p = self._txrx(CMD_GET_POWER)
        if len(p) >= 2 and p[0] == 0:
            d["on"] = bool(p[1])
        d["zones"] = self.length
        return d
