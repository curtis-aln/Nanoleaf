"""`--probe`: USB diagnostics plus a colour test sweep, then exit."""
from __future__ import annotations

import time

from .constants import PID, VID
from .devices.hid_descriptor import parse_hid_descriptor
from .devices.usb import StripDevice, _get_descriptor, load_hid
from .errors import DeviceError
from .procs import find_nanoleaf_apps


def probe(report_id=None, report_size=None) -> int:
    hid, problem = load_hid()
    if hid is None:
        print(problem)
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

    apps = find_nanoleaf_apps()
    if apps:
        print(f"WARNING: {', '.join(apps)} is running and will fight this script - quit it and re-run.")

    dev = StripDevice(report_id, report_size)
    ok, msg = dev.connect()
    print("\nconnect:", msg)
    if not ok:
        print("Include this whole output when reporting a problem.")
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
              "still wrong - try --report-size.")
    except DeviceError as e:
        print("error:", e)
        return 1
    finally:
        try:
            dev.set_pixels([(0, 0, 0)] * dev.length)
        except DeviceError:
            pass
        dev.close()
    print("Did the strip cycle red, green, blue, white? If so, you're good.")
    return 0
