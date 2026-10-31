"""The I/O thread: the only code that talks to the strip.

Fail-safe behaviour:
* reconnects with exponential backoff if the strip disappears or errors,
* a frame is only marked "sent" after the device accepted it, so a failed write is retried,
* wrong-length frames are resampled, and the optional power limiter is applied here,
* if the producer stops delivering frames (engine crash/hang) the strip is blanked rather than
  frozen on its last colour,
* on shutdown the strip is blanked and powered down unless the user chose "leave".
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Optional

from .devices.base import BaseDevice
from .errors import DeviceError
from .frame import Frame, black, limit_power, sanitize
from .settings import SettingsStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Status:
    text: str = "Starting..."
    ok: bool = False
    simulated: bool = False
    fps: float = 0.0
    warn: str = ""
    app_msg: str = ""
    last_button: str = ""
    info: Dict[str, object] = field(default_factory=dict)


class Worker(threading.Thread):
    def __init__(self, dev: BaseDevice, store: SettingsStore, fps: float, watcher=None,
                 stale_timeout: float = 4.0):
        super().__init__(name="strip-io", daemon=True)
        self.dev, self.store, self.watcher = dev, store, watcher
        self.interval = 1.0 / fps
        self.stale_timeout = stale_timeout
        self.length = dev.length
        self.on_button: Optional[Callable[[bytes], None]] = None
        dev.on_button = self._handle_button

        self._lock = threading.Lock()
        self._frame: Optional[Frame] = None
        self._seq = self._sent_seq = 0
        self._submitted_at = time.monotonic()
        self._status = Status(simulated=dev.simulated)
        self._halt = threading.Event()
        self._exit_mode = "off"
        self._applied = None            # (power, brightness) last pushed to the strip
        self._resend = False
        self._blanked = False
        self._backoff = 0.5
        self._reject = ""

    # -- public API (any thread) -------------------------------------------
    def submit(self, frame: Frame) -> None:
        with self._lock:
            self._frame, self._seq = frame, self._seq + 1
            self._submitted_at = time.monotonic()

    def status(self) -> Status:
        return self._status

    def stop(self, on_exit: str = "off") -> None:
        self._exit_mode = on_exit
        self._halt.set()
        if self.ident is not None:
            self.join(timeout=3.0)
            if self.is_alive():
                log.warning("I/O thread did not stop in time")
        else:
            self.dev.close()

    # -- internals ----------------------------------------------------------
    def _set(self, **kw) -> None:
        with self._lock:
            self._status = replace(self._status, **kw)

    def _handle_button(self, body: bytes) -> None:
        self._set(last_button=body.hex() or "press")
        if self.on_button:
            try:
                self.on_button(body)
            except Exception:  # noqa: BLE001
                log.exception("button handler failed")

    def run(self) -> None:
        try:
            self._loop()
        except Exception:  # noqa: BLE001 - last resort; _loop already handles per-iteration errors
            log.exception("I/O thread crashed")
            self._set(text="I/O thread crashed - see log", ok=False)
        finally:
            self._finalise()

    def _loop(self) -> None:
        count, t0 = 0, time.monotonic()
        while not self._halt.is_set():
            if not self.dev.connected:
                if not self._connect():
                    continue
                count, t0 = 0, time.monotonic()
            tick = time.monotonic()
            try:
                if self._step():
                    count += 1
            except DeviceError as e:
                self._lost(str(e))
                continue
            except Exception as e:  # noqa: BLE001 - treat any surprise like a dropped link
                log.exception("unexpected I/O error")
                self._lost(f"unexpected error: {e!r}")
                continue
            now = time.monotonic()
            if now - t0 >= 1.0:
                self._set(fps=count / (now - t0))
                count, t0 = 0, now
            msg = self.watcher.message if (self.watcher and not self.dev.simulated) else ""
            if msg != self._status.app_msg:
                self._set(app_msg=msg)
            self._halt.wait(max(0.0, self.interval - (time.monotonic() - tick)))

    def _connect(self) -> bool:
        self._set(ok=False, fps=0.0)
        try:
            ok, msg = self.dev.connect()
        except Exception as e:  # noqa: BLE001
            log.exception("connect crashed")
            ok, msg = False, f"connect failed: {e!r}"
        if not ok:
            self._set(text=msg)
            delay = self._backoff * random.uniform(0.8, 1.2)
            self._backoff = min(self._backoff * 2, 5.0)
            self._halt.wait(delay)
            return False
        self._backoff = 0.5
        self.length = self.dev.length
        self._applied, self._resend, self._blanked = None, True, False
        try:
            info = self.dev.info()
        except Exception:  # noqa: BLE001 - info is cosmetic
            info = {"zones": self.dev.length}
        self._set(text=msg, ok=True, info=info)
        return True

    def _lost(self, why: str) -> None:
        self._set(text=f"Lost device: {why}", ok=False, fps=0.0)
        self.dev.close()
        self._halt.wait(0.3)

    def _step(self) -> bool:
        s = self.store.get()
        power = s.power
        bri = min(s.brightness, s.max_brightness)
        prev = self._applied
        if prev is None or prev[0] != power:
            self.dev.set_power(power)
            self._resend = self._resend or power
        if power and (prev is None or prev[1] != bri or not prev[0]):
            self.dev.set_brightness(bri)
        self._applied = (power, bri)
        if not power:
            return False

        with self._lock:
            frame, seq, age = self._frame, self._seq, time.monotonic() - self._submitted_at
        n = self.dev.length

        if age > self.stale_timeout:                      # dead-man switch
            if not self._blanked:
                self.dev.set_pixels(black(n))
                self._blanked = True
                self._set(warn="animation engine stalled - strip blanked")
            return False
        if self._blanked:
            self._blanked, self._resend = False, True
            self._set(warn=self._reject)

        if frame is None or (seq == self._sent_seq and not self._resend):
            return False
        code = self.dev.set_pixels(limit_power(sanitize(frame, n), s.power_limit))
        self._sent_seq, self._resend = seq, False         # only after the device accepted it
        reject = "frame rejected (strip off / brightness 0?)" if code else ""
        if reject != self._reject:
            self._reject = reject
            self._set(warn=reject)
        return True

    def _finalise(self) -> None:
        if self.dev.connected:
            try:
                if self._exit_mode == "off":
                    self.dev.set_pixels(black(self.dev.length))
                    self.dev.set_power(False)
            except Exception:  # noqa: BLE001
                log.debug("could not blank the strip on exit", exc_info=True)
        self.dev.close()
