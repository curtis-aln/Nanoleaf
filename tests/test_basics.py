import json
import tempfile
import unittest
from pathlib import Path

from nanoleaf_strip.devices.hid_descriptor import parse_hid_descriptor
from nanoleaf_strip.frame import crossfade, limit_power, parse_color, sanitize
from nanoleaf_strip.layout import Layout, zone_positions
from nanoleaf_strip.settings import Settings, SettingsStore, load_settings

VENDOR_DESC = bytes.fromhex("0600ff0901a101150026ff00750895400901810209019102c0")


class HidDescriptor(unittest.TestCase):
    def test_unnumbered_reports(self):
        out, inp = parse_hid_descriptor(VENDOR_DESC)
        self.assertEqual(out, {0: 64})
        self.assertEqual(inp, {0: 64})

    def test_numbered_reports(self):
        desc = bytes.fromhex("0600ff0901a1018501150026ff00750895400901810209019102c0")
        out, inp = parse_hid_descriptor(desc)
        self.assertEqual(out, {1: 64})


class Frames(unittest.TestCase):
    def test_sanitize_clamps_and_resamples(self):
        self.assertEqual(sanitize([(300, -5, 7.9)], 1), [(255, 0, 7)])
        self.assertEqual(len(sanitize([(1, 2, 3)] * 10, 75)), 75)
        self.assertEqual(sanitize([], 3), [(0, 0, 0)] * 3)

    def test_limit_power(self):
        white = [(255, 255, 255)] * 10
        self.assertEqual(limit_power(white, 1.0), white)
        out = limit_power(white, 0.5)
        self.assertLessEqual(sum(sum(p) for p in out), 10 * 765 * 0.5 + 10)
        self.assertEqual(limit_power([(10, 10, 10)] * 4, 0.5), [(10, 10, 10)] * 4)

    def test_crossfade_endpoints(self):
        a, b = [(0, 0, 0)], [(200, 100, 0)]
        self.assertEqual(crossfade(a, b, 0), a)
        self.assertEqual(crossfade(a, b, 1), b)

    def test_parse_color(self):
        self.assertEqual(parse_color("#00aaff"), (0, 170, 255))
        self.assertEqual(parse_color("f80"), (255, 136, 0))
        self.assertEqual(parse_color("1, 2,3"), (1, 2, 3))
        with self.assertRaises(ValueError):
            parse_color("nope")


class LayoutTests(unittest.TestCase):
    def test_default_matches_original_perimeter(self):
        # first LED sits half a step along the top edge, last LED on the left edge, going up
        pts = zone_positions(75, 100, 50)
        self.assertEqual(pts[0][2], 0)
        self.assertEqual(pts[-1][2], 3)
        self.assertAlmostEqual(pts[0][0], 0.5 / 75 * 300)

    def test_start_corner_and_direction(self):
        cw = zone_positions(8, 100, 100, Layout("tl", True))
        ccw = zone_positions(8, 100, 100, Layout("tl", False))
        self.assertEqual(cw[0][2], 0)     # starts on the top edge
        self.assertEqual(ccw[0][2], 3)    # runs the other way: starts on the left edge
        br = zone_positions(8, 100, 100, Layout("br", True))
        self.assertEqual(br[0][2], 2)     # bottom edge

    def test_offset_rotates(self):
        a = zone_positions(10, 100, 50, Layout(offset=0))
        b = zone_positions(10, 100, 50, Layout(offset=3))
        self.assertEqual(b[0], a[3])


class SettingsTests(unittest.TestCase):
    def test_clamping(self):
        s = Settings(speed=99, brightness=-3, on_exit="weird", start="zz", power_limit=0).sanitised()
        self.assertEqual((s.speed, s.brightness, s.on_exit, s.start), (4.0, 1, "off", "tl"))
        self.assertGreater(s.power_limit, 0)

    def test_roundtrip_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "c.json"
            st = SettingsStore(path=p)
            st.update(effect="Fire", color=(1, 2, 3), speed=2.5)
            self.assertTrue(st.save())
            self.assertEqual([f.name for f in p.parent.iterdir()], ["c.json"])   # no temp litter
            back = load_settings(p)
            self.assertEqual((back.effect, back.color, back.speed), ("Fire", (1, 2, 3), 2.5))

    def test_corrupt_file_is_set_aside(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text("{not json")
            self.assertEqual(load_settings(p), Settings())
            self.assertTrue(p.with_suffix(".bad").exists())

    def test_unknown_keys_ignored_and_unknown_update_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"effect": "Plasma", "future_field": 1, "color": "garbage"}))
            self.assertEqual(load_settings(p).effect, "Plasma")
        with self.assertRaises(AttributeError):
            SettingsStore().update(nope=1)


if __name__ == "__main__":
    unittest.main()
