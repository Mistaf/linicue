"""Measure the mouse's real polling rate (read-only): move the mouse fast in circles while it runs.

    linicue pollrate [seconds]      # default 6

Counts the mouse's own movement reports on its hidraw node and prints the busiest second.
At 1000 Hz expect about 900-1000, at 500 Hz about 450-500, at 250 Hz about 230-250, at 125 Hz about 120-125.
"""
import os
import select
import sys
import time

from .nxp import find_button_node


def peak_rate(times: list[float], window: float = 1.0) -> float:
    """Most reports that fall inside any half-open `window` seconds, per second (a closed window counts one too many)."""
    best = lo = 0
    for hi, t in enumerate(times):
        while t - times[lo] >= window:
            lo += 1
        best = max(best, hi - lo + 1)
    return best / window


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    seconds = float(argv[0]) if argv else 6.0
    node = find_button_node()
    if not node:
        print("Scimitar not found (plugged in? udev rule installed?)")
        return 1
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    print(f"Move the mouse fast in circles for {seconds:.0f} seconds ...")
    times, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        if select.select([fd], [], [], 0.05)[0]:
            data = os.read(fd, 4096)
            if data and data[0] == 1:  # report id 1 = pointer movement and buttons
                times.append(time.monotonic())
    print(f"{len(times)} reports; busiest second: {peak_rate(times):.0f} per second")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
