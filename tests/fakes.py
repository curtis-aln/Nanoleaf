"""Test doubles: a fake `hid` module whose device speaks the strip's TLV protocol."""
from __future__ import annotations

import collections
import time

from nanoleaf_strip.devices.base import BaseDevice
from nanoleaf_strip.errors import DeviceError


class FakeHidDevice:
    """Behaves like hid.device(): fixed-size output reports, replies queued for read()."""

    def __init__(self, report_size=64, report_id=0, zones=75, descriptor=b"", frames=None):
        self.size, self.rid, self.zones = report_size, report_id, zones
        self.descriptor = descriptor
        self.frames = frames if frames is not None else []
        self.replies = collections.deque()
        self.writes = 0
        self.fail_writes = False
        self._buf, self._expected = b"", 0
        self.power = None
        self.bri = None

    def open_path(self, path): pass
    def close(self): pass
    def get_report_descriptor(self): return list(self.descriptor)

    def write(self, data):
        if self.fail_writes:
            return -1
        if len(data) != self.size + 1:        # real devices reject wrong-sized reports
            return -1
        if data[0] != self.rid:
            return -1
        self.writes += 1
        chunk = bytes(data[1:])
        if not self._buf:
            self._expected = 3 + ((chunk[1] << 8) | chunk[2])
        self._buf += chunk
        if len(self._buf) >= self._expected:
            self._handle(self._buf[:self._expected])
            self._buf, self._expected = b"", 0
        return len(data)

    def _reply(self, mtype, payload):
        msg = bytes([0x80 + mtype, len(payload) >> 8, len(payload) & 0xFF]) + payload
        msg = msg.ljust(self.size, b"\0")
        self.replies.append((bytes([self.rid]) + msg) if self.rid else msg)

    def _handle(self, msg):
        mtype, payload = msg[0], msg[3:]
        if mtype == 0x03:
            self._reply(mtype, bytes([0, self.zones]))
        elif mtype == 0x02:
            self.frames.append([tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)])
            self._reply(mtype, bytes([0]))
        elif mtype == 0x07:
            self.power = bool(payload[0]); self._reply(mtype, bytes([0]))
        elif mtype == 0x09:
            self.bri = payload[0]; self._reply(mtype, bytes([0]))
        elif mtype == 0x0C:
            self._reply(mtype, bytes([0]) + b"NL82K2")
        elif mtype == 0x0A:
            self._reply(mtype, bytes([0, 0x12]))
        elif mtype == 0x08:
            self._reply(mtype, bytes([0, self.bri or 0]))
        elif mtype == 0x06:
            self._reply(mtype, bytes([0, 1 if self.power else 0]))

    def push_button_event(self, body=b"\x01"):
        msg = bytes([0x85, 0, len(body)]) + body
        msg = msg.ljust(self.size, b"\0")
        self.replies.appendleft((bytes([self.rid]) + msg) if self.rid else msg)

    def read(self, n, timeout_ms=0):
        if self.replies:
            return list(self.replies.popleft())
        time.sleep(min(timeout_ms, 5) / 1000)
        return []


class FakeHidModule:
    def __init__(self, dev):
        self.dev = dev

    def enumerate(self, vid, pid):
        return [{"path": b"fake", "interface_number": 0, "usage_page": 0xFF00, "usage": 1}]

    def device(self):
        return self.dev


class FlakyDevice(BaseDevice):
    """Records everything; can be told to fail connects or writes."""
    simulated = True

    def __init__(self, zones=75):
        super().__init__()
        self.length = zones
        self.frames, self.powers, self.bris = [], [], []
        self.fail_connect = 0
        self.fail_next_pixels = 0
        self.connects = 0

    def connect(self):
        self.connects += 1
        if self.fail_connect > 0:
            self.fail_connect -= 1
            return False, "not found"
        self.connected = True
        return True, "ok"

    def close(self): self.connected = False

    def set_pixels(self, rgb):
        if self.fail_next_pixels > 0:
            self.fail_next_pixels -= 1
            raise DeviceError("boom")
        self.frames.append(list(rgb))
        return 0

    def set_power(self, on): self.powers.append(on)
    def set_brightness(self, value): self.bris.append(value)


def wait_for(cond, timeout=3.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()
