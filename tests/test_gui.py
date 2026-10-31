import os
import unittest

try:
    from PIL import Image
    from nanoleaf_strip.gui.render import PreviewRenderer
except ImportError:      # pragma: no cover
    PreviewRenderer = None

from nanoleaf_strip.layout import Layout


@unittest.skipIf(PreviewRenderer is None, "Pillow not installed")
class RendererTests(unittest.TestCase):
    def test_renders_any_led_count_and_brightness(self):
        r = PreviewRenderer(900, 500, 1.0)
        for n in (1, 3, 75, 144):
            for k in (0.0, 0.4, 1.0):
                img = r.render([(255, 60, 0)] * n, k, Layout("br", False, 5))
                self.assertEqual(img.size, (900, 500))

    def test_glow_lights_the_backdrop(self):
        r = PreviewRenderer(900, 500, 1.0)
        dark = r.render([(0, 0, 0)] * 75, 1.0)
        lit = r.render([(255, 0, 0)] * 75, 1.0)
        x, y = int(r.led_rect[0]) - 12, int(r.h * 0.4)     # just outside the strip
        self.assertGreater(lit.getpixel((x, y))[0], dark.getpixel((x, y))[0] + 15)

    def test_tiny_window_does_not_crash(self):
        PreviewRenderer(50, 50, 1.0).render([(1, 2, 3)] * 75, 1.0)


@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display (try: xvfb-run python -m unittest)")
class WindowSmoke(unittest.TestCase):
    def test_window_opens_updates_and_closes(self):
        from nanoleaf_strip.devices import SimDevice
        from nanoleaf_strip.gui.app import App
        from nanoleaf_strip.runtime import Runtime
        from nanoleaf_strip.settings import SettingsStore
        rt = Runtime(SettingsStore(), SimDevice(), 30)
        rt.start()
        app = App(rt, 30)
        app.root.after(400, lambda: (rt.cycle_effect(1), app.root.after(300, app._request_close)))
        app.run()
        rt.stop()
        self.assertNotEqual(rt.store.get().effect, "Rainbow wave")


if __name__ == "__main__":
    unittest.main()
