#!/usr/bin/env python3
"""
Nanoleaf PC Screen Mirror Lightstrip (NL82K2) - custom controller + live visualiser.

    pip install hidapi

    python nanoleaf_strip.py            # drive the real strip over USB HID
    python nanoleaf_strip.py --sim      # GUI only, no hardware needed
    python nanoleaf_strip.py --probe    # USB diagnostics + RGB test sweep, then exit

Quit the Nanoleaf Desktop app first so it isn't fighting you for the device.

Protocol: Nanoleaf "USB Lightstrip Communication Protocol" (VID 0x37FA, PID 0x8202).
Messages are TLV: [type:1][length:2 big-endian][payload], reply type = 0x80 + type.
"""
from __future__ import annotations

import argparse
import colorsys
import math
import random
import subprocess
import sys
import threading
import time

try:
    import hid  # pip install hidapi
except ImportError:
    hid = None

VID, PID = 0x37FA, 0x8202
IS_WINDOWS = sys.platform.startswith("win")

CMD_SET_RGB = 0x02
CMD_GET_LEN = 0x03
CMD_GET_POWER = 0x06
CMD_SET_POWER = 0x07
CMD_GET_BRI = 0x08
CMD_SET_BRI = 0x09
CMD_GET_FW = 0x0A
CMD_GET_MODEL = 0x0C
EVT_BUTTON = 0x85


# --------------------------------------------------------------------------- #
# Device layer
# --------------------------------------------------------------------------- #
class DeviceError(Exception):
    pass


def parse_hid_descriptor(desc):
    """Minimal HID report-descriptor walk -> ({report_id: out_bytes}, {report_id: in_bytes}).
    Sizes exclude the report-id byte. report_id 0 means 'unnumbered reports'."""
    out, inp = {}, {}
    g = {"size": 0, "count": 0, "rid": 0}
    stack = []
    desc = bytes(desc)
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:  # long item, unused in practice
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
    fix = lambda d: {k: (v + 7) // 8 for k, v in d.items() if v > 0}
    return fix(out), fix(inp)


def _get_descriptor(h):
    try:
        return bytes(h.get_report_descriptor())
    except Exception:
        return b""


def nanoleaf_app_running():
    """True if the Nanoleaf Desktop app is running - it also streams to the strip and causes flicker."""
    try:
        if IS_WINDOWS:
            r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                               timeout=5, creationflags=0x08000000)  # CREATE_NO_WINDOW
        else:
            r = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=5)
        return "nanoleaf" in r.stdout.lower()
    except Exception:  # noqa: BLE001
        return False


class StripDevice:
    """Real strip over USB HID. Only ever touched from the worker thread."""
    simulated = False

    def __init__(self, report_id=None, report_size=None, on_button=None):
        self.force = None
        if report_id is not None or report_size is not None:
            self.force = (report_id or 0, report_size or 64)
        self.on_button = on_button
        self.h = None
        self.rid, self.size = 0, 64
        self.length = 75
        self.chunks = 1
        self.connected = False
        self.detail = ""

    # -- connection ---------------------------------------------------------
    @staticmethod
    def _detect_size_windows(h, rid):
        """Windows hidapi zero-pads writes shorter than the device's output report and fails longer ones,
        so the largest write length that succeeds IS the report length. Probes with harmless GET_LEN
        messages. Returns data bytes per report (excluding the id byte) or None."""
        hdr = bytes([CMD_GET_LEN, 0, 0])

        def ok(d):
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

    def _candidates(self, h):
        cands = []
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

    def connect(self):
        if hid is None:
            return False, "hidapi not installed (pip install hidapi)"
        infos = hid.enumerate(VID, PID)
        if not infos:
            return False, "Strip not found on USB (37FA:8202) - replug it?"
        last = "no HID interface answered the length query"
        for info in infos:
            h = hid.device()
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

    def close(self):
        self.connected = False
        if self.h is not None:
            try:
                self.h.close()
            except Exception:  # noqa: BLE001
                pass
            self.h = None

    # -- transport ----------------------------------------------------------
    def _write_msg(self, msg):
        for i in range(0, len(msg), self.size):
            chunk = msg[i:i + self.size].ljust(self.size, b"\0")
            if self.h.write(bytes([self.rid]) + chunk) < 0:
                raise DeviceError("USB write failed")

    def _txrx(self, mtype, payload=b"", timeout=250):
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
                    if self.on_button:
                        self.on_button(body)
                    continue
                if rtype == 0x80 + mtype:
                    return body
        except (OSError, ValueError) as e:
            raise DeviceError(str(e)) from e

    # -- commands -----------------------------------------------------------
    def set_pixels(self, rgb):
        payload = bytes(max(0, min(255, int(v))) for px in rgb for v in px)
        pl = self._txrx(CMD_SET_RGB, payload, timeout=150)
        return pl[0] if pl else 1  # 0 = success

    def set_power(self, on):
        self._txrx(CMD_SET_POWER, bytes([1 if on else 0]))

    def set_brightness(self, value):
        self._txrx(CMD_SET_BRI, bytes([max(0, min(255, int(value)))]))

    def info(self):
        d = {}
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


class SimDevice:
    """Same interface as StripDevice, no hardware."""
    simulated = True

    def __init__(self, note="Simulation (no hardware)"):
        self.note = note
        self.connected = False
        self.length = 75

    def connect(self):
        self.connected = True
        return True, self.note

    def close(self):
        self.connected = False

    def set_pixels(self, rgb):
        return 0

    def set_power(self, on):
        pass

    def set_brightness(self, value):
        pass


class Worker(threading.Thread):
    """Owns the device; streams the newest frame at ~fps and applies power/brightness changes."""

    def __init__(self, dev, fps):
        super().__init__(daemon=True)
        self.dev, self.interval = dev, 1.0 / fps
        self.lock = threading.Lock()
        self.frame, self.seq, self.sent_seq = None, 0, 0
        self.power, self.bri, self.dirty = True, 110, True
        self.status, self.warn, self.app_msg = "Connecting...", "", ""
        self.ok, self.fps = False, 0.0
        self.length = dev.length
        self._halt = threading.Event()

    def submit(self, frame):
        with self.lock:
            self.frame, self.seq = frame, self.seq + 1

    def set_power(self, on):
        with self.lock:
            self.power, self.dirty = bool(on), True

    def set_brightness(self, v):
        with self.lock:
            self.bri, self.dirty = int(v), True

    def stop(self):
        self._halt.set()
        self.join(timeout=1.5)
        self.dev.close()

    def _check_app(self):
        if not self.dev.simulated:
            self.app_msg = ("Nanoleaf Desktop is running - quit it (system tray / Task Manager) "
                            "or it overwrites frames" if nanoleaf_app_running() else "")

    def run(self):
        count, t0, last_app = 0, time.monotonic(), 0.0
        while not self._halt.is_set():
            if time.monotonic() - last_app > 5:
                last_app = time.monotonic()
                threading.Thread(target=self._check_app, daemon=True).start()
            if not self.dev.connected:
                self.ok = False
                ok, msg = self.dev.connect()
                self.status = msg
                if not ok:
                    self._halt.wait(1.5)
                    continue
                self.length = self.dev.length
                with self.lock:
                    self.dirty = True
            tick = time.monotonic()
            try:
                with self.lock:
                    frame = self.frame if self.seq != self.sent_seq else None
                    self.sent_seq = self.seq
                    power, bri, dirty = self.power, self.bri, self.dirty
                    self.dirty = False
                if dirty:
                    self.dev.set_power(power)
                    if power:
                        self.dev.set_brightness(bri)
                if frame is not None and power:
                    code = self.dev.set_pixels(frame)
                    self.warn = "frame rejected (strip off / brightness 0?)" if code else ""
                    count += 1
                self.ok = True
            except DeviceError as e:
                self.status, self.ok, self.fps = f"Lost device: {e}", False, 0.0
                self.dev.close()
                continue
            if time.monotonic() - t0 >= 1.0:
                self.fps, count, t0 = count / (time.monotonic() - t0), 0, time.monotonic()
            self._halt.wait(max(0.0, self.interval - (time.monotonic() - tick)))


# --------------------------------------------------------------------------- #
# Effects: render(n_zones, phase, dt, base_colour) -> [(r, g, b), ...]
# --------------------------------------------------------------------------- #
def hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def scale(c, k):
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


class Rainbow:
    name = "Rainbow wave"

    def render(self, n, ph, dt, color):
        return [hsv(i / n * 1.5 - ph * 0.25) for i in range(n)]


class Plasma:
    name = "Plasma"

    def render(self, n, ph, dt, color):
        out = []
        for i in range(n):
            x = i / n
            v = math.sin(x * 9 + ph * 1.1) + math.sin(x * 5 - ph * 0.8) + math.sin((x + ph * 0.1) * 13)
            out.append(hsv(0.5 + v / 6 + ph * 0.03, 0.9, 0.75 + 0.25 * math.sin(x * 7 + ph)))
        return out


class Comet:
    name = "Comet"

    def render(self, n, ph, dt, color):
        head, tail = (ph * 14) % n, max(4.0, n * 0.18)
        out = []
        for i in range(n):
            d = (head - i) % n
            c = scale(color, math.exp(-d / tail))
            w = max(0.0, 1 - d / 2.0)
            out.append(tuple(int(v + (255 - v) * w) for v in c))
        return out


class Fire:
    name = "Fire"

    def __init__(self):
        self.heat = []

    @staticmethod
    def _ramp(x):
        t = int(max(0.0, min(1.0, x)) * 191)
        r = (t & 0x3F) << 2
        if t > 128:
            return (255, 255, r)
        if t > 64:
            return (255, r, 0)
        return (r, 0, 0)

    def render(self, n, ph, dt, color):
        if len(self.heat) != n:
            self.heat = [0.0] * n
        f = dt * 30
        h = self.heat
        for i in range(n):
            h[i] = max(0.0, h[i] - random.uniform(0, 0.06) * f)
        h[:] = [(h[i - 1] + 2 * h[i] + h[(i + 1) % n]) / 4 for i in range(n)]
        if random.random() < min(1.0, 0.3 * f):
            j = random.randrange(n)
            h[j] = min(1.0, h[j] + random.uniform(0.5, 1.0))
        return [self._ramp(x) for x in h]


class Breathing:
    name = "Breathing"

    def render(self, n, ph, dt, color):
        k = 0.06 + 0.94 * ((math.sin(ph * 2.2) + 1) / 2) ** 2
        return [scale(color, k)] * n


class Solid:
    name = "Solid colour"

    def render(self, n, ph, dt, color):
        return [tuple(color)] * n


EFFECTS = [Rainbow(), Plasma(), Comet(), Fire(), Breathing(), Solid()]


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
def perimeter_points(n, x0, y0, x1, y1):
    """n points spaced evenly around a rectangle, clockwise from the top-left corner."""
    w, h = x1 - x0, y1 - y0
    per, pts = 2 * (w + h), []
    for i in range(n):
        d = (i + 0.5) / n * per
        if d < w:
            pts.append((x0 + d, y0))
        elif d < w + h:
            pts.append((x1, y0 + d - w))
        elif d < 2 * w + h:
            pts.append((x1 - (d - w - h), y1))
        else:
            pts.append((x0, y1 - (d - 2 * w - h)))
    return pts


def run_gui(worker, fps):
    import tkinter as tk
    from tkinter import colorchooser, ttk

    BG, PANEL, FG, DIM = "#0b0b10", "#15151d", "#e8e8f0", "#8a8a9a"
    BGRGB = (11, 11, 16)
    W, H = 900, 440

    hexc = lambda c: "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c)
    mix = lambda c, a: hexc(tuple(BGRGB[i] * (1 - a) + c[i] * a for i in range(3)))

    root = tk.Tk()
    root.title("Nanoleaf Lightstrip Controller")
    root.configure(bg=BG)
    root.resizable(False, False)

    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=FG)
    st.configure("Horizontal.TScale", background=PANEL, troughcolor="#2a2a38")
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)

    effects = {e.name: e for e in EFFECTS}
    effect_var = tk.StringVar(value=EFFECTS[0].name)
    speed_var = tk.DoubleVar(value=1.0)
    bri_var = tk.DoubleVar(value=110)
    power_var = tk.BooleanVar(value=True)
    state = {"color": (0, 170, 255)}

    # ---- controls
    bar = tk.Frame(root, bg=PANEL)
    bar.pack(fill="x")
    pad = {"padx": 10, "pady": 6}
    lbl = lambda parent, t: tk.Label(parent, text=t, bg=PANEL, fg=DIM, font=("Segoe UI", 9))

    lbl(bar, "Effect").grid(row=0, column=0, sticky="w", **pad)
    ttk.Combobox(bar, textvariable=effect_var, values=list(effects), state="readonly", width=16
                 ).grid(row=0, column=1, sticky="w", **pad)

    swatch = tk.Label(bar, width=3, bg=hexc(state["color"]))

    def pick():
        c = colorchooser.askcolor(color=hexc(state["color"]), parent=root)
        if c and c[0]:
            state["color"] = tuple(int(v) for v in c[0])
            swatch.config(bg=hexc(state["color"]))

    tk.Button(bar, text="Colour...", command=pick, bg="#2a2a38", fg=FG, relief="flat",
              activebackground="#3a3a4c", activeforeground=FG).grid(row=0, column=2, **pad)
    swatch.grid(row=0, column=3, sticky="w", **pad)
    tk.Checkbutton(bar, text="Power", variable=power_var, command=lambda: worker.set_power(power_var.get()),
                   bg=PANEL, fg=FG, selectcolor=PANEL, activebackground=PANEL, activeforeground=FG
                   ).grid(row=0, column=4, **pad)

    lbl(bar, "Speed").grid(row=1, column=0, sticky="w", **pad)
    ttk.Scale(bar, from_=0.1, to=4.0, variable=speed_var, length=200).grid(row=1, column=1, columnspan=2, sticky="w", **pad)
    lbl(bar, "Brightness").grid(row=1, column=3, sticky="e", **pad)
    ttk.Scale(bar, from_=1, to=255, variable=bri_var, length=200,
              command=lambda v: worker.set_brightness(float(v))).grid(row=1, column=4, **pad)

    status_row = tk.Frame(root, bg=BG)
    status_row.pack(fill="x", padx=12, pady=(8, 0))
    dot = tk.Label(status_row, text="\u25CF", bg=BG, fg="#ff5c5c", font=("Segoe UI", 12))
    dot.pack(side="left")
    status = tk.Label(status_row, text="", bg=BG, fg=FG, font=("Segoe UI", 10))
    status.pack(side="left", padx=6)

    # ---- preview canvas
    cv = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
    cv.pack()
    mon = (260, 70, 640, 284)
    led_rect = (mon[0] - 22, mon[1] - 22, mon[2] + 22, mon[3] + 22)
    cv.create_rectangle(*mon, fill="#050508", outline="#2a2a38", width=2)
    cv.create_text(W / 2, (mon[1] + mon[3]) / 2, text="monitor", fill="#22222e", font=("Segoe UI", 22))
    cv.create_text(30, 340, anchor="w", fill=DIM, font=("Segoe UI", 9),
                   text="Data order, LED 0 \u2192 N-1 (this is exactly what is sent over USB)")
    cv.create_text(W / 2, 420, fill="#44445a", font=("Segoe UI", 8),
                   text="Preview wraps the zones clockwise from top-left; your real strip's start corner depends on how you mounted it.")

    items = {"glow": [], "bar": []}

    def build(n):
        cv.delete("leds")
        items["glow"], items["bar"] = [], []
        for x, y in perimeter_points(n, *led_rect):
            items["glow"].append([
                cv.create_oval(x - r, y - r, x + r, y + r, fill=BG, outline="", tags="leds") for r in (20, 13, 6)])
        bw = (W - 60) / n
        for i in range(n):
            items["bar"].append(cv.create_rectangle(
                30 + i * bw, 360, 30 + (i + 1) * bw - 1, 392, fill=BG, outline="", tags="leds"))

    def paint(frame, k):
        for ids, px in zip(items["glow"], frame):
            c = (px[0] * k, px[1] * k, px[2] * k)
            cv.itemconfig(ids[0], fill=mix(c, 0.14))
            cv.itemconfig(ids[1], fill=mix(c, 0.38))
            cv.itemconfig(ids[2], fill=hexc(c))
        for rid, px in zip(items["bar"], frame):
            cv.itemconfig(rid, fill=hexc((px[0] * k, px[1] * k, px[2] * k)))

    n = worker.length
    build(n)
    last, phase, last_txt = time.perf_counter(), 0.0, ""
    interval_ms = max(1, int(1000 / fps) - 3)

    def tick():
        nonlocal n, last, phase, last_txt
        now = time.perf_counter()
        dt, last = min(now - last, 0.1), now
        phase += dt * speed_var.get()
        if worker.length != n:
            n = worker.length
            build(n)
        frame = effects[effect_var.get()].render(n, phase, dt, state["color"])
        worker.submit(frame)
        paint(frame, bri_var.get() / 255 if power_var.get() else 0.0)

        txt = worker.status + (f"  |  {worker.fps:.0f} fps sent" if worker.ok and not worker.dev.simulated else "")
        if worker.warn:
            txt += f"  |  {worker.warn}"
        if worker.app_msg:
            txt += f"  |  {worker.app_msg}"
        if txt != last_txt:
            status.config(text=txt)
            dot.config(fg="#f5a623" if worker.dev.simulated else ("#3ddc84" if worker.ok else "#ff5c5c"))
            last_txt = txt
        root.after(interval_ms, tick)

    def on_close():
        worker.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    tick()
    root.mainloop()


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #
def probe(args):
    if hid is None:
        print("hidapi is not installed:  pip install hidapi")
        return 1
    infos = hid.enumerate(VID, PID)
    print(f"{len(infos)} HID interface(s) for {VID:04X}:{PID:04X}")
    for info in infos:
        print(f"  path={info['path']!r} iface={info.get('interface_number')} "
              f"usage_page=0x{info.get('usage_page', 0):04X} usage=0x{info.get('usage', 0):04X}")
        h = hid.device()
        try:
            h.open_path(info["path"])
        except Exception as e:  # noqa: BLE001
            print(f"    open failed: {e}  (quit Nanoleaf Desktop?)")
            continue
        desc = _get_descriptor(h)
        if desc:
            print(f"    report descriptor ({len(desc)} B): {desc.hex()}")
            out, inp = parse_hid_descriptor(desc)
            print(f"    output reports {out}  input reports {inp}   (id 0 = unnumbered)")
        else:
            print("    report descriptor not available from this hidapi build")
        h.close()
    if not infos:
        return 1

    dev = StripDevice(args.report_id, args.report_size)
    ok, msg = dev.connect()
    print("\nconnect:", msg)
    if nanoleaf_app_running():
        print("WARNING: Nanoleaf Desktop is running and will fight this script - quit it "
              "(system tray / Task Manager) and re-run.")
    if not ok:
        print("Paste this whole output back to me and I'll adjust the framing.")
        return 1
    try:
        print("device info:", dev.info())
        dev.set_power(True)
        dev.set_brightness(128)
        for name, c in (("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255)), ("white", (255, 255, 255))):
            code = dev.set_pixels([c] * dev.length)
            print(f"  {name:5s} -> reply code {code} (0 = success)")
            time.sleep(0.8)
        n = dev.length
        for i in range(n):  # a single white dot should travel the WHOLE strip
            dev.set_pixels([(255, 255, 255) if j == i else (0, 0, 60) for j in range(n)])
            time.sleep(0.03)
        print(f"  chase over {n} zones done. If only the first ~20 LEDs ever lit, the report size is "
              "still wrong - paste this output to me.")
    except DeviceError as e:
        print("error:", e)
        return 1
    finally:
        dev.close()
    print("Did the strip cycle red, green, blue, white? If so, you're good.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", action="store_true", help="simulate the strip (GUI only)")
    ap.add_argument("--probe", action="store_true", help="print USB diagnostics, run a colour test, exit")
    ap.add_argument("--fps", type=int, default=30, help="target frame rate (default 30)")
    ap.add_argument("--report-id", type=int, default=None, help="override HID output report id")
    ap.add_argument("--report-size", type=int, default=None, help="override HID report payload size in bytes")
    args = ap.parse_args()

    if args.probe:
        sys.exit(probe(args))

    if args.sim:
        dev = SimDevice()
    elif hid is None:
        print("hidapi missing -> running in simulation. Install with:  pip install hidapi")
        dev = SimDevice("hidapi not installed - simulating (pip install hidapi)")
    else:
        dev = StripDevice(args.report_id, args.report_size)

    fps = max(5, min(args.fps, 60))
    worker = Worker(dev, fps)
    worker.start()
    try:
        run_gui(worker, fps)
    except ImportError as e:
        worker.stop()
        sys.exit(f"tkinter is required for the GUI: {e}")


if __name__ == "__main__":
    main()