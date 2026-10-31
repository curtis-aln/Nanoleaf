"""Command line entry point."""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

from . import __version__
from .constants import DEFAULT_FPS, MAX_FPS, MIN_FPS
from .devices import SimDevice, StripDevice, load_hid
from .effects import build_effects, unavailable_effects
from .frame import parse_color
from .instance import InstanceLock
from .runtime import Runtime
from .settings import SettingsStore, default_config_path, load_settings

DESCRIPTION = """\
Nanoleaf PC Screen Mirror Lightstrip (NL82K2) - custom controller + live visualiser.

  python run.py                    drive the real strip over USB HID, with the GUI
  python run.py --sim              GUI only, no hardware needed
  python run.py --headless --effect Fire     no window; Ctrl+C to quit
  python run.py --probe            USB diagnostics + RGB test sweep, then exit

Quit the Nanoleaf Desktop app first so it isn't fighting you for the device.
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    mode = ap.add_argument_group("mode")
    mode.add_argument("--sim", action="store_true", help="simulate the strip (no hardware)")
    mode.add_argument("--headless", action="store_true", help="run without the GUI")
    mode.add_argument("--probe", action="store_true", help="print USB diagnostics, run a colour test, exit")
    mode.add_argument("--list-effects", action="store_true", help="print the available effects and exit")

    look = ap.add_argument_group("look (remembered between runs)")
    look.add_argument("--effect", help="effect name, e.g. Fire or 'Screen mirror'")
    look.add_argument("--color", help="primary colour: #rrggbb or r,g,b")
    look.add_argument("--color2", help="secondary colour (Gradient effect)")
    look.add_argument("--speed", type=float, help="animation speed 0.1-4.0")
    look.add_argument("--brightness", type=int, help="strip brightness 1-255")

    safe = ap.add_argument_group("safety (remembered between runs)")
    safe.add_argument("--on-exit", choices=("off", "leave"), help="what to do with the strip on quit (default: off)")
    safe.add_argument("--max-brightness", type=int, help="hard ceiling for hardware brightness, 1-255")
    safe.add_argument("--power-limit", type=float, help="cap total LED draw, 0.05-1.0 (1.0 = no cap)")
    safe.add_argument("--button-action", choices=("cycle", "none"), help="what the strip's physical button does")

    adv = ap.add_argument_group("advanced")
    adv.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"target frame rate (default {DEFAULT_FPS})")
    adv.add_argument("--report-id", type=int, default=None, help="override HID output report id")
    adv.add_argument("--report-size", type=int, default=None, help="override HID report payload size in bytes")
    adv.add_argument("--config", type=Path, default=None, help="settings file (default: per-user config dir)")
    adv.add_argument("--no-save", action="store_true", help="do not read or write the settings file")
    adv.add_argument("--force", action="store_true", help="skip the one-copy-at-a-time check")
    adv.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    return ap


def _apply_overrides(store: SettingsStore, args, effects) -> Optional[str]:
    changes = {}
    try:
        if args.effect:
            match = {n.lower(): n for n in effects}.get(args.effect.lower())
            if match is None:
                return f"unknown effect {args.effect!r}. Available: {', '.join(effects)}"
            changes["effect"] = match
        if args.color:
            changes["color"] = parse_color(args.color)
        if args.color2:
            changes["color2"] = parse_color(args.color2)
    except ValueError as e:
        return f"bad colour: {e}"
    for opt, key in (("speed", "speed"), ("brightness", "brightness"), ("on_exit", "on_exit"),
                     ("max_brightness", "max_brightness"), ("power_limit", "power_limit"),
                     ("button_action", "button_action")):
        v = getattr(args, opt)
        if v is not None:
            changes[key] = v
    store.update(**changes)
    return None


def _headless_loop(rt: Runtime) -> None:
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, lambda *_: stop.set())
    print("Running headless - press Ctrl+C to quit.")
    last = ""
    while not stop.wait(0.5):
        st = rt.worker.status()
        line = st.text + (f" | {st.fps:.0f} fps" if st.ok and not st.simulated else "")
        for extra in (st.warn, st.app_msg, rt.engine.error):
            if extra:
                line += f" | {extra}"
        if line != last:
            print(line)
            last = line


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=[logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbose, 2)],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.probe:
        from .diagnostics import probe
        return probe(args.report_id, args.report_size)

    effects = build_effects()
    if args.list_effects:
        print("\n".join(effects))
        for name, why in unavailable_effects():
            print(f"{name}  (unavailable: {why})")
        return 0

    path = None if args.no_save else (args.config or default_config_path())
    store = SettingsStore(load_settings(path), path)
    problem = _apply_overrides(store, args, effects)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    fps = max(MIN_FPS, min(args.fps, MAX_FPS))
    lock = None
    if args.sim:
        dev = SimDevice()
    else:
        hid, why = load_hid()
        if hid is None:
            print(f"{why} -> running in simulation.", file=sys.stderr)
            dev = SimDevice(f"{why} - simulating")
        else:
            dev = StripDevice(args.report_id, args.report_size)
            lock = InstanceLock()
            if not args.force and not lock.acquire():
                print("Another copy of this program is already controlling the strip. "
                      "Close it first (or use --force).", file=sys.stderr)
                return 3

    rt = Runtime(store, dev, fps, effects)
    rt.start()
    try:
        if args.headless:
            _headless_loop(rt)
        else:
            try:
                import tkinter  # noqa: F401
            except ImportError as e:
                print(f"tkinter is required for the GUI ({e}). Use --headless, or install python3-tk.",
                      file=sys.stderr)
                return 1
            from .gui.app import run_gui
            try:
                run_gui(rt, fps)
            except tkinter.TclError as e:
                print(f"Could not open a window ({e}). Use --headless on machines without a display.",
                      file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop()
        if lock:
            lock.release()
    return 0
