import time
import unittest

from nanoleaf_strip.effects import build_effects
from nanoleaf_strip.effects.base import Effect
from nanoleaf_strip.engine import Engine
from nanoleaf_strip.runtime import Runtime
from nanoleaf_strip.settings import SettingsStore
from nanoleaf_strip.worker import Worker

from .fakes import FlakyDevice, wait_for


def start_worker(dev, store=None, fps=60, stale=4.0):
    store = store or SettingsStore()
    w = Worker(dev, store, fps, stale_timeout=stale)
    w.start()
    return w, store


class WorkerTests(unittest.TestCase):
    def test_streams_latest_frame_and_applies_power_brightness(self):
        dev = FlakyDevice()
        w, store = start_worker(dev)
        w.submit([(1, 2, 3)] * 75)
        self.assertTrue(wait_for(lambda: dev.frames))
        self.assertEqual(dev.frames[-1][0], (1, 2, 3))
        self.assertEqual(dev.powers[0], True)
        self.assertEqual(dev.bris[-1], 110)
        store.update(brightness=200)
        self.assertTrue(wait_for(lambda: dev.bris[-1] == 200))
        w.stop("leave")

    def test_max_brightness_ceiling(self):
        dev = FlakyDevice()
        store = SettingsStore()
        store.update(brightness=250, max_brightness=100)
        w, _ = start_worker(dev, store)
        w.submit([(0, 0, 0)] * 75)
        self.assertTrue(wait_for(lambda: dev.bris))
        self.assertEqual(dev.bris[-1], 100)
        w.stop("leave")

    def test_failed_send_is_retried_not_lost(self):
        dev = FlakyDevice()
        dev.fail_next_pixels = 1
        w, _ = start_worker(dev)
        w.submit([(5, 5, 5)] * 75)               # submitted once only
        self.assertTrue(wait_for(lambda: dev.frames), "frame was dropped after a failed write")
        self.assertEqual(dev.frames[0][0], (5, 5, 5))
        self.assertGreaterEqual(dev.connects, 2)  # it reconnected
        w.stop("leave")

    def test_reconnects_with_backoff_and_recovers(self):
        dev = FlakyDevice()
        dev.fail_connect = 2
        w, _ = start_worker(dev)
        w.submit([(1, 1, 1)] * 75)
        self.assertTrue(wait_for(lambda: dev.frames, timeout=5))
        self.assertTrue(w.status().ok)
        w.stop("leave")

    def test_wrong_length_frame_is_fitted(self):
        dev = FlakyDevice(zones=75)
        w, _ = start_worker(dev)
        w.submit([(9, 9, 9)] * 10)
        self.assertTrue(wait_for(lambda: dev.frames))
        self.assertEqual(len(dev.frames[-1]), 75)
        w.stop("leave")

    def test_power_limit_applied(self):
        dev = FlakyDevice()
        store = SettingsStore()
        store.update(power_limit=0.25)
        w, _ = start_worker(dev, store)
        w.submit([(255, 255, 255)] * 75)
        self.assertTrue(wait_for(lambda: dev.frames))
        self.assertLessEqual(sum(sum(p) for p in dev.frames[-1]), 75 * 765 * 0.25 + 75)
        w.stop("leave")

    def test_dead_mans_switch_blanks_stalled_strip_and_recovers(self):
        dev = FlakyDevice()
        w, _ = start_worker(dev, stale=0.3)
        w.submit([(200, 0, 0)] * 75)
        self.assertTrue(wait_for(lambda: dev.frames))
        self.assertTrue(wait_for(lambda: dev.frames[-1][0] == (0, 0, 0), timeout=2))
        self.assertIn("stalled", w.status().warn)
        w.submit([(0, 200, 0)] * 75)
        self.assertTrue(wait_for(lambda: dev.frames[-1][0] == (0, 200, 0)))
        self.assertEqual(w.status().warn, "")
        w.stop("leave")

    def test_exit_modes(self):
        for mode, expect_off in (("off", True), ("leave", False)):
            dev = FlakyDevice()
            w, _ = start_worker(dev)
            w.submit([(255, 0, 0)] * 75)
            wait_for(lambda: dev.frames)
            w.stop(mode)
            self.assertEqual(dev.powers[-1] is False, expect_off, mode)
            if expect_off:
                self.assertEqual(dev.frames[-1][0], (0, 0, 0))
            self.assertFalse(dev.connected)

    def test_power_off_stops_frames(self):
        dev = FlakyDevice()
        w, store = start_worker(dev)
        w.submit([(1, 1, 1)] * 75)
        wait_for(lambda: dev.frames)
        store.update(power=False)
        wait_for(lambda: dev.powers[-1] is False)
        n = len(dev.frames)
        w.submit([(2, 2, 2)] * 75)
        time.sleep(0.15)
        self.assertEqual(len(dev.frames), n)
        store.update(power=True)                  # turning back on pushes the newest frame
        self.assertTrue(wait_for(lambda: dev.frames[-1][0] == (2, 2, 2)))
        w.stop("leave")

    def test_button_events_update_status(self):
        dev = FlakyDevice()
        w, _ = start_worker(dev)
        seen = []
        w.on_button = seen.append
        wait_for(lambda: dev.connected)
        dev.on_button(b"\x09")
        self.assertEqual(seen, [b"\x09"])
        self.assertEqual(w.status().last_button, "09")
        w.stop("leave")


class Boom(Effect):
    name = "Boom"

    def render(self, ctx):
        raise RuntimeError("kaboom")


class Probe(Effect):
    name = "Probe"
    uses_color = True

    def __init__(self):
        self.log = []
        self.last_ctx = None

    def activate(self): self.log.append("on")
    def deactivate(self): self.log.append("off")

    def render(self, ctx):
        self.last_ctx = ctx
        return [ctx.color] * ctx.n


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.dev = FlakyDevice()
        self.store = SettingsStore()
        self.worker = Worker(self.dev, self.store, 60)
        self.worker.start()
        wait_for(lambda: self.dev.connected)

    def tearDown(self):
        self.worker.stop("leave")

    def test_broken_effect_goes_dark_and_loop_survives(self):
        self.store.update(effect="Boom")
        eng = Engine(self.store, self.worker, {"Boom": Boom(), "Solid colour": Probe()}, 60)
        eng.start()
        self.assertTrue(wait_for(lambda: "kaboom" in eng.error))
        self.assertEqual(eng.preview()[0], (0, 0, 0))
        self.store.update(effect="Solid colour", fade=0)      # recovers by switching
        self.assertTrue(wait_for(lambda: eng.error == ""))
        eng.stop()

    def test_effect_lifecycle_and_speed_scaling(self):
        a, b = Probe(), Probe()
        self.store.update(effect="A", speed=2.0, fade=0)
        eng = Engine(self.store, self.worker, {"A": a, "Solid colour": b}, 60)
        eng.start()
        self.assertTrue(wait_for(lambda: a.last_ctx is not None))
        ctx = a.last_ctx
        self.assertAlmostEqual(ctx.dt, ctx.real_dt * 2.0, places=6)   # Fire & co. now honour speed
        self.store.update(effect="Solid colour")
        self.assertTrue(wait_for(lambda: b.last_ctx is not None))
        eng.stop()
        self.assertEqual(a.log, ["on", "off"])
        self.assertEqual(b.log, ["on", "off"])

    def test_crossfade_is_gradual(self):
        a, b = Probe(), Probe()
        self.store.update(effect="A", color=(255, 255, 255), fade=0.4)
        eng = Engine(self.store, self.worker, {"A": a, "Solid colour": b}, 60)
        eng.start()
        wait_for(lambda: a.last_ctx)
        b_color = (0, 0, 0)
        self.store.update(effect="Solid colour", color=b_color)
        seen = set()
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            seen.add(eng.preview()[0][0])
            time.sleep(0.01)
        eng.stop()
        self.assertTrue(any(0 < v < 255 for v in seen), f"no intermediate values: {sorted(seen)[:5]}")


class RuntimeTests(unittest.TestCase):
    def test_button_cycles_effects_with_debounce(self):
        rt = Runtime(SettingsStore(), FlakyDevice(), 30, build_effects())
        first = rt.store.get().effect
        rt._on_button(b"\x01")
        second = rt.store.get().effect
        rt._on_button(b"\x00")            # release right after press: ignored
        self.assertNotEqual(first, second)
        self.assertEqual(rt.store.get().effect, second)

    def test_button_action_none(self):
        rt = Runtime(SettingsStore(), FlakyDevice(), 30, build_effects())
        rt.store.update(button_action="none")
        before = rt.store.get().effect
        rt._on_button(b"\x01")
        self.assertEqual(rt.store.get().effect, before)

    def test_start_stop_blanks_strip(self):
        dev = FlakyDevice()
        rt = Runtime(SettingsStore(), dev, 60, build_effects())
        rt.start()
        self.assertTrue(wait_for(lambda: len(dev.frames) > 3))
        rt.stop()
        self.assertEqual(dev.frames[-1][0], (0, 0, 0))
        self.assertEqual(dev.powers[-1], False)


if __name__ == "__main__":
    unittest.main()
