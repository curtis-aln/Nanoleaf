"""Detect the Nanoleaf Desktop app, which also streams to the strip and causes flicker."""
from __future__ import annotations

import csv
import os
import subprocess
import threading
from typing import List, Tuple

from .constants import IS_WINDOWS


def list_processes() -> List[Tuple[str, int]]:
    """[(name, pid), ...] for running processes; empty if the listing fails."""
    try:
        if IS_WINDOWS:
            r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                               timeout=5, creationflags=0x08000000)  # CREATE_NO_WINDOW
            rows = []
            for row in csv.reader(r.stdout.splitlines()):
                if len(row) >= 2 and row[1].isdigit():
                    rows.append((row[0], int(row[1])))
            return rows
        r = subprocess.run(["ps", "-A", "-o", "pid=,comm="], capture_output=True, text=True, timeout=5)
        rows = []
        for line in r.stdout.splitlines():
            pid, _, name = line.strip().partition(" ")
            if pid.isdigit():
                rows.append((name.strip(), int(pid)))
        return rows
    except Exception:  # noqa: BLE001
        return []


def find_nanoleaf_apps() -> List[str]:
    """Names of other running processes that look like Nanoleaf software (never this one)."""
    me = {os.getpid(), os.getppid()}
    found = {name for name, pid in list_processes() if "nanoleaf" in name.lower() and pid not in me}
    return sorted(found)


def nanoleaf_app_running() -> bool:
    return bool(find_nanoleaf_apps())


class AppWatcher(threading.Thread):
    """Polls the process list every few seconds; `message` is '' when all is well."""

    def __init__(self, interval: float = 5.0):
        super().__init__(name="app-watch", daemon=True)
        self.interval = interval
        self.message = ""
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            apps = find_nanoleaf_apps()
            self.message = (f"{', '.join(apps)} is running - quit it (system tray / Task Manager) "
                            "or it overwrites frames") if apps else ""
            self._halt.wait(self.interval)

    def stop(self) -> None:
        self._halt.set()
