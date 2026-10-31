"""Exception types shared across the package."""
from __future__ import annotations


class DeviceError(Exception):
    """The strip could not be reached, or stopped answering."""
