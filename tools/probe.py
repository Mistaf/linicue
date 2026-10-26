"""Read-only probe for the Scimitar RGB Elite (1b1c:1b8b).  Sends nothing to the device.

    sudo python3 tools/probe.py            # list its input/hidraw interfaces and HID report descriptors
    sudo python3 tools/probe.py --watch    # also log events while you press buttons (Ctrl-C to stop)

Everything is also written to probe-output.txt (or --out FILE); send that file back so the
button map can be built from facts.
"""
import glob
import os
import select
import struct
import sys

VID, PID = "1b1c", "1b8b"


def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None


def input_nodes():
    out = []
    for d in glob.glob("/sys/class/input/event*"):
        dev = d + "/device"
        if read(dev + "/id/vendor") == VID and read(dev + "/id/product") == PID:
            out.append((os.path.basename(d), read(dev + "/name"), read(dev + "/phys")))
    return sorted(out)


def hidraw_nodes():
    out = []
    for d in glob.glob("/sys/class/hidraw/hidraw*"):
        uevent = read(d + "/device/uevent") or ""
        if f"0000{VID}:0000{PID}" in uevent.lower():  # HID_ID=0003:00001B1C:00001B8B
            desc = open(d + "/device/report_descriptor", "rb").read() if os.path.exists(d + "/device/report_descriptor") else b""
            out.append((os.path.basename(d), desc))
    return sorted(out)


def main():
    path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "probe-output.txt"
    out = open(path, "w")

    def log(line, echo=True):
        out.write(line + "\n")
        out.flush()  # keep what was captured if Ctrl-C comes mid-write
        if echo:
            print(line)

    nodes, raws = input_nodes(), hidraw_nodes()
    if not nodes and not raws:
        log(f"no {VID}:{PID} device found (is the mouse plugged in? is this the right model?)")
        return 1
    for n, name, phys in nodes:
        log(f"input  /dev/input/{n}  name={name!r} phys={phys}")
    for n, desc in raws:
        log(f"hidraw /dev/{n}  report descriptor ({len(desc)} bytes): {desc.hex()}")
    if "--watch" not in sys.argv:
        print(f"saved to {path}")
        return 0
    fds = {}
    for n, *_ in nodes:
        fds[os.open(f"/dev/input/{n}", os.O_RDONLY | os.O_NONBLOCK)] = f"input/{n}"
    for n, _ in raws:
        fds[os.open(f"/dev/{n}", os.O_RDONLY | os.O_NONBLOCK)] = n
    print(f"watching; press every button once (G1-G12, DPI, wheel, tilt); events go to {path}. Ctrl-C when done.")
    ev = struct.Struct("llHHi")
    while True:
        for fd in select.select(list(fds), [], [])[0]:
            data = os.read(fd, 4096)
            if fds[fd].startswith("input/"):
                for i in range(0, len(data) - ev.size + 1, ev.size):
                    _, _, t, c, v = ev.unpack_from(data, i)
                    if t:
                        log(f"{fds[fd]}: type={t} code={c} value={v}", echo=False)
            else:
                log(f"{fds[fd]}: {data.hex()}", echo=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
