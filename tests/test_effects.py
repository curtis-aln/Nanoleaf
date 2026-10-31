import unittest

from nanoleaf_strip.effects import ALL_EFFECTS
from nanoleaf_strip.effects.base import RenderContext
from nanoleaf_strip.effects.classic import Fire
from nanoleaf_strip.effects.screen import GRID_COLS, GRID_ROWS, ScreenMirror
from nanoleaf_strip.layout import Layout, zone_positions
from nanoleaf_strip.settings import Settings

try:
    from PIL import Image
except ImportError:      # pragma: no cover
    Image = None


def ctx(n=75, phase=1.0, dt=1 / 30, layout=Layout(), settings=Settings()):
    return RenderContext(n, phase, dt, dt, (0, 170, 255), (255, 70, 170), layout, settings)


class EveryEffect(unittest.TestCase):
    def test_valid_output_for_many_sizes_and_times(self):
        for cls in ALL_EFFECTS:
            if cls.name == "Screen mirror":
                continue
            eff = cls()
            eff.activate()
            for n in (1, 2, 7, 75, 144):
                for k in range(40):
                    out = eff.render(ctx(n=n, phase=k * 0.37, dt=0.033))
                    self.assertEqual(len(out), n, cls.name)
                    for p in out:
                        self.assertEqual(len(p), 3, cls.name)
                        self.assertTrue(all(isinstance(v, int) and 0 <= v <= 255 for v in p), (cls.name, p))
            eff.deactivate()

    def test_fire_ramp_band_edges(self):
        self.assertEqual(Fire._ramp(0.0), (0, 0, 0))
        r = Fire._ramp(0.34)          # t=64 -> second band starts exactly at 64
        self.assertEqual(r[0], 255)
        self.assertEqual(Fire._ramp(1.0)[:2], (255, 255))

    def test_fire_speed_changes_cooling(self):
        import random
        def total_heat(dt):
            random.seed(3)
            f = Fire()
            f.heat = [0.8] * 30
            f.render(ctx(n=30, dt=dt))
            return sum(f.heat)
        self.assertGreater(total_heat(0.001), total_heat(0.3))


@unittest.skipIf(Image is None, "Pillow not installed")
class ScreenMirrorTests(unittest.TestCase):
    def make(self, paint):
        img = Image.new("RGB", (GRID_COLS, GRID_ROWS))
        px = img.load()
        for x in range(GRID_COLS):
            for y in range(GRID_ROWS):
                px[x, y] = paint(x, y)
        return lambda: ((lambda c, r: (img, (1920, 1080))), lambda: None)

    def run_effect(self, paint, layout=Layout(), n=75):
        eff = ScreenMirror(source_factory=self.make(paint))
        eff.activate()
        import time
        end = time.monotonic() + 2
        while eff._grabber.latest() is None and time.monotonic() < end:
            time.sleep(0.01)
        s = Settings(screen_response=60.0)
        out = None
        for _ in range(30):
            out = eff.render(ctx(n=n, layout=layout, settings=s))
        eff.deactivate()
        return out

    def test_edge_colours_land_on_the_right_leds(self):
        # left third red, right third blue, middle black
        def paint(x, y):
            return (255, 0, 0) if x < GRID_COLS // 3 else (0, 0, 255) if x >= 2 * GRID_COLS // 3 else (0, 0, 0)
        out = self.run_effect(paint)
        pos = zone_positions(75, 1920, 1080, Layout())
        for (x, y, side), px in zip(pos, out):
            if side == 3:           # left edge
                self.assertGreater(px[0], 150, (x, y, px))
                self.assertLess(px[2], 60)
            if side == 1:           # right edge
                self.assertGreater(px[2], 150, (x, y, px))
                self.assertLess(px[0], 60)

    def test_layout_changes_mapping(self):
        def paint(x, y):
            return (255, 255, 255) if y < GRID_ROWS // 4 else (0, 0, 0)     # bright band along the top
        cw = self.run_effect(paint, Layout("tl", True))
        ccw = self.run_effect(paint, Layout("tl", False))
        self.assertGreater(sum(cw[10]), 300)     # LED 10 is along the top edge when clockwise from top-left
        self.assertLess(sum(ccw[10]), 100)       # ...but well down the left edge when counter-clockwise

    def test_capture_failure_surfaces_as_error(self):
        def bad():
            raise OSError("no display")
        eff = ScreenMirror(source_factory=bad)
        eff.activate()
        import time
        time.sleep(0.2)
        with self.assertRaises(RuntimeError):
            eff.render(ctx())
        eff.deactivate()


if __name__ == "__main__":
    unittest.main()
