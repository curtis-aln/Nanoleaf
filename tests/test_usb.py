import unittest

from nanoleaf_strip.devices.usb import StripDevice
from nanoleaf_strip.errors import DeviceError

from .fakes import FakeHidDevice, FakeHidModule
from .test_basics import VENDOR_DESC


def make(**kw):
    fake = FakeHidDevice(**kw)
    return fake, StripDevice(hid_module=FakeHidModule(fake))


class UsbProtocol(unittest.TestCase):
    def test_connect_from_descriptor_and_multichunk_frame(self):
        fake, dev = make(report_size=64, descriptor=VENDOR_DESC)
        ok, msg = dev.connect()
        self.assertTrue(ok, msg)
        self.assertEqual((dev.size, dev.length, dev.chunks), (64, 75, 4))
        frame = [(i, 255 - i, 7) for i in range(75)]
        self.assertEqual(dev.set_pixels(frame), 0)
        self.assertEqual(fake.frames[-1], frame)          # reassembled across 4 reports, intact

    def test_connect_without_descriptor_falls_back_to_guessing(self):
        fake, dev = make(report_size=32, descriptor=b"")
        ok, msg = dev.connect()
        self.assertTrue(ok, msg)
        self.assertEqual(dev.size, 32)

    def test_numbered_reports(self):
        fake, dev = make(report_size=63, report_id=1, descriptor=b"")
        ok, msg = dev.connect()
        self.assertTrue(ok, msg)
        self.assertEqual((dev.rid, dev.size), (1, 63))
        self.assertEqual(dev.set_pixels([(9, 9, 9)] * 75), 0)

    def test_info(self):
        fake, dev = make(descriptor=VENDOR_DESC)
        dev.connect()
        dev.set_power(True)
        dev.set_brightness(90)
        info = dev.info()
        self.assertEqual((info["model"], info["firmware"], info["brightness"], info["on"], info["zones"]),
                         ("NL82K2", "1.2", 90, True, 75))

    def test_button_event_is_forwarded_not_mistaken_for_reply(self):
        fake, dev = make(descriptor=VENDOR_DESC)
        dev.connect()
        seen = []
        dev.on_button = seen.append
        fake.push_button_event(b"\x07")
        dev.set_brightness(10)
        self.assertEqual(seen, [b"\x07"])
        self.assertEqual(fake.bri, 10)

    def test_broken_button_callback_does_not_break_streaming(self):
        fake, dev = make(descriptor=VENDOR_DESC)
        dev.connect()
        dev.on_button = lambda b: 1 / 0
        fake.push_button_event()
        dev.set_brightness(11)

    def test_write_failure_raises_device_error(self):
        fake, dev = make(descriptor=VENDOR_DESC)
        dev.connect()
        fake.fail_writes = True
        with self.assertRaises(DeviceError):
            dev.set_pixels([(0, 0, 0)] * 75)

    def test_closed_device_raises_cleanly(self):
        fake, dev = make(descriptor=VENDOR_DESC)
        dev.connect()
        dev.close()
        with self.assertRaises(DeviceError):
            dev.set_power(True)

    def test_missing_hid_gives_helpful_message(self):
        dev = StripDevice(hid_module=None)
        dev._hid, dev._hid_problem = None, "hidapi not installed"
        self.assertEqual(dev.connect(), (False, "hidapi not installed"))


if __name__ == "__main__":
    unittest.main()
