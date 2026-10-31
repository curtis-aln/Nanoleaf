"""Refuse to start a second copy: two programs streaming to one strip makes it flicker."""
from __future__ import annotations

import socket

from .constants import INSTANCE_PORT


class InstanceLock:
    def __init__(self, port: int = INSTANCE_PORT):
        self.port = port
        self._sock = None

    def acquire(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", self.port))   # no SO_REUSEADDR on purpose: a second bind must fail
        except OSError:
            s.close()
            return False
        self._sock = s
        return True

    def release(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
