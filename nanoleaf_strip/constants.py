"""Protocol constants and app-wide defaults."""
from __future__ import annotations

import sys

APP_NAME = "nanoleaf-strip"

# USB identity of the PC Screen Mirror Lightstrip (NL82K2)
VID, PID = 0x37FA, 0x8202

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# TLV command ids. A reply's type is 0x80 + the command id.
CMD_SET_RGB = 0x02
CMD_GET_LEN = 0x03
CMD_GET_POWER = 0x06
CMD_SET_POWER = 0x07
CMD_GET_BRI = 0x08
CMD_SET_BRI = 0x09
CMD_GET_FW = 0x0A
CMD_GET_MODEL = 0x0C
EVT_BUTTON = 0x85  # unsolicited event from the strip's physical button

DEFAULT_ZONES = 75
DEFAULT_FPS = 60
MIN_FPS, MAX_FPS = 5, 60

# Localhost port used purely as a "one copy at a time" lock.
INSTANCE_PORT = 47823
