"""Decode the Scimitar RGB Elite's vendor button report (hidraw0, report id 0x03, 63-byte bitmap).

Layout seen in a capture from a real mouse (payload = bytes after the id):
  payload[1] bits 0-7 -> G1..G8,  payload[2] bits 0-3 -> G9..G12,  payload[0] bits 5,6 -> the two top buttons.
The kernel ignores this report, so the buttons need no grab: read the hidraw node and diff reports.
"""
from __future__ import annotations

import asyncio
import errno
import os
from typing import Callable

REPORT_ID = 3
# shortcut: which top button is which is unconfirmed (0x20 first pressed, then 0x40); swap if wrong
TOP_BUTTONS = {0x20: "MouseDpiToggle", 0x40: "MouseProfileSwitch"}


def pressed_buttons(report: bytes) -> set[str]:
    if len(report) < 4 or report[0] != REPORT_ID:
        return set()
    d = report[1:]
    out = {f"MouseG{i + 1}" for i in range(8) if d[1] >> i & 1}
    out |= {f"MouseG{9 + i}" for i in range(4) if d[2] >> i & 1}
    out |= {name for bit, name in TOP_BUTTONS.items() if d[0] & bit}
    return out


class ButtonTracker:
    """Turns successive reports into (button, pressed) edges."""

    def __init__(self) -> None:
        self.down: set[str] = set()

    def update(self, report: bytes) -> list[tuple[str, bool]]:
        if not report or report[0] != REPORT_ID:
            return []
        now = pressed_buttons(report)
        edges = [(b, True) for b in sorted(now - self.down)] + [(b, False) for b in sorted(self.down - now)]
        self.down = now
        return edges


def watch(path: str, on_edge: Callable[[str, bool], None], on_error: Callable[[Exception], None] = lambda e: None) -> Callable[[], None]:
    """Read *path* (e.g. /dev/hidraw0) on the running loop; returns a function that stops it.

    When the device goes away (read error or end of file) the reader is removed and on_error is called once."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    tracker = ButtonTracker()
    loop = asyncio.get_running_loop()
    closed = False

    def stop() -> None:
        nonlocal closed
        if not closed:
            closed = True
            loop.remove_reader(fd)
            os.close(fd)

    def ready() -> None:
        try:
            data = os.read(fd, 4096)
            if not data:
                raise OSError(errno.ENODEV, "device closed")
        except BlockingIOError:
            return
        except OSError as e:
            stop()
            on_error(e)
            return
        for edge in tracker.update(data):
            on_edge(*edge)

    loop.add_reader(fd, ready)
    return stop
