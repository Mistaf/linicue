"""Corsair NXP packets for the Scimitar RGB Elite (1b1c:1b8b), control channel = hidraw with usage page 0xFFC2.

Byte layout and constants come from iCUE's LegacyProtocols.dll (decompiled; fields 0x05 and 0x22) and agree with
ckb-next's nxp_proto.h.  Reports are 64 bytes with no report id: write them as-is to the hidraw node.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

REPORT_LEN = 64
CMD_SET = 0x07
FIELD_SPECIAL = 0x04  # button handling: hardware vs software
FIELD_LIGHTING = 0x05  # lighting control: hardware vs software + hardware brightness level 0..3
FIELD_POLLRATE = 0x0A  # polling interval in ms at payload[4]; the mouse re-enumerates on USB afterwards
FIELD_MOUSE = 0x13  # mouse subcommands
MOUSE_DPI, MOUSE_SNAP, MOUSE_DPIMASK, MOUSE_DPIPROF = 0x02, 0x04, 0x05, 0xD0  # current stage / enabled-stage bitmask / stage values (|stage)
FIELD_M_COLOR = 0x22  # per-zone colours
MODE_HARDWARE, MODE_SOFTWARE = 0x01, 0x02
MAX_ZONES = 15  # 4 header bytes + 4 bytes per zone must fit in 64
# Not used here: the 20-triple + G*0.7333/B*0.6 layout in iCUE's FUN_18009b610 is the *mousepad* (NxpMousePadBacklightFeature).


def _pad(*b: int) -> bytes:
    return bytes(b).ljust(REPORT_LEN, b"\0")


def special_mode(software: bool) -> bytes:
    return _pad(CMD_SET, FIELD_SPECIAL, MODE_SOFTWARE if software else MODE_HARDWARE)


def lighting_control(software: bool, level: int = 3) -> bytes:
    """level is the mouse's own brightness (0-3 = 0/33/66/100 %); keep 3 and scale colours in software."""
    if not 0 <= level <= 3:
        raise ValueError("hardware brightness level is 0..3")
    return _pad(CMD_SET, FIELD_LIGHTING, MODE_SOFTWARE if software else MODE_HARDWARE, 0, level)


POLLING_MS = {125: 8, 250: 4, 500: 2, 1000: 1}  # Hz -> interval, the table iCUE uses


def polling_rate(hz: int) -> bytes:
    if hz not in POLLING_MS:
        raise ValueError(f"polling rate must be one of {sorted(POLLING_MS)} Hz")
    return _pad(CMD_SET, FIELD_POLLRATE, 0, 0, POLLING_MS[hz])


def angle_snapping(enabled: bool, angle: int = 5) -> bytes:
    """`07 13 04 00 <enabled> <angle>`; byte 3 = 0 is a live change (1 would save it in the mouse)."""
    if not 0 <= angle <= 255:
        raise ValueError("angle is one byte")
    return _pad(CMD_SET, FIELD_MOUSE, MOUSE_SNAP, 0, int(enabled), angle)


def dpi_stage(stage: int, x: int, y: int | None = None) -> bytes:
    """Set the DPI of a stage (0 = sniper, 1..5 = modes); volatile (byte 3 = 0), ckb-next layout."""
    y = x if y is None else y
    if not (0 <= stage <= 5 and 0 < x <= 0xFFFF and 0 < y <= 0xFFFF):
        raise ValueError("stage 0..5, dpi 1..65535")
    return _pad(CMD_SET, FIELD_MOUSE, MOUSE_DPIPROF | stage, 0, int(x != y), x & 0xFF, x >> 8, y & 0xFF, y >> 8)


def dpi_mask(stages: set[int]) -> bytes:
    return _pad(CMD_SET, FIELD_MOUSE, MOUSE_DPIMASK, 0, sum(1 << s for s in stages))


def dpi_select(stage: int) -> bytes:
    return _pad(CMD_SET, FIELD_MOUSE, MOUSE_DPI, 0, stage)


def mouse_colors(zones: dict[int, tuple[int, int, int]], flag: int = 1) -> bytes:
    """`07 22 <n> 01` then `<zone> R G B` per zone (iCUE NxpMouseBacklightFeature, FUN_18009a560).

    Zone ids come from the device module; ckb-next numbers the Scimitar's from 1 (front, back, dpi, wheel, thumb, side).
    """
    if not 0 < len(zones) <= MAX_ZONES:
        raise ValueError(f"1..{MAX_ZONES} zones per packet")
    buf = bytearray(_pad(CMD_SET, FIELD_M_COLOR, len(zones), flag))
    for i, (zone, (r, g, b)) in enumerate(sorted(zones.items())):
        if not 0 <= zone <= 255 or not all(0 <= c <= 255 for c in (r, g, b)):
            raise ValueError("zone id and colour components are 0..255")
        buf[4 + i * 4: 8 + i * 4] = bytes((zone, r, g, b))
    return bytes(buf)


def find_hidraw(match, sys_root: str | Path = "/sys/class/hidraw", vid: str = "1b1c", pid: str = "1b8b") -> str | None:
    """First hidraw node of our device whose report descriptor satisfies match(descriptor)."""
    for d in sorted(Path(sys_root).glob("hidraw*")):
        try:
            uevent = (d / "device/uevent").read_text().lower()
            desc = (d / "device/report_descriptor").read_bytes()
        except OSError:
            continue
        if f"0000{vid}:0000{pid}" in uevent and match(desc):
            return f"/dev/{d.name}"
    return None


def find_control_node(sys_root: str | Path = "/sys/class/hidraw", vid: str = "1b1c", pid: str = "1b8b") -> str | None:
    """Control interface: descriptor starts with usage page 0xFFC2 (06 c2 ff)."""
    return find_hidraw(lambda d: d.startswith(bytes.fromhex("06c2ff")), sys_root, vid, pid)


def find_button_node(sys_root: str | Path = "/sys/class/hidraw", vid: str = "1b1c", pid: str = "1b8b") -> str | None:
    """Mouse interface that carries the vendor button report 0x03 (usage page 0xFFC1)."""
    return find_hidraw(lambda d: bytes.fromhex("06c1ff") in d and not d.startswith(bytes.fromhex("06c2ff")), sys_root, vid, pid)


class ControlChannel:
    def __init__(self, path: str | None = None):
        self.path = path or find_control_node()
        if not self.path:
            raise FileNotFoundError("Scimitar control interface not found (is the udev rule installed?)")
        self.fd = os.open(self.path, os.O_RDWR)

    def send(self, packet: bytes) -> None:
        if len(packet) != REPORT_LEN:
            raise ValueError("packets are 64 bytes")
        os.write(self.fd, packet)
        try:  # drain any acknowledgement so the kernel buffer never fills
            os.set_blocking(self.fd, False)
            os.read(self.fd, REPORT_LEN)
        except BlockingIOError:
            pass
        finally:
            os.set_blocking(self.fd, True)

    def close(self) -> None:
        os.close(self.fd)


# How to take software control and number zones. `ckb` is the one verified on a Scimitar RGB Elite.
#   name: (setup packets, first zone id, byte 3 of the colour packet)
VARIANTS = {
    "ckb": ([special_mode(True)], 1, 1),  # ckb-next, and iCUE gates colours on operating mode = software (field 4)
    "openrgb": ([lighting_control(True, 1)], 0, 0),  # OpenRGB
    "icue-lighting": ([lighting_control(True)], 1, 1),  # first attempt: turned the lights off, no zone lit
}


def lights_cli(args: list[str]) -> int:
    """python -m linicue lights [--send] [--variant ckb|openrgb|icue-lighting] [--identify | --zone N] [--color RRGGBB] [--restore]"""
    send = "--send" in args
    color = args[args.index("--color") + 1] if "--color" in args else "ff0000"
    rgb = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    if "--restore" in args:
        plan = [("buttons -> mouse", special_mode(False)), ("lighting -> mouse", lighting_control(False))]
    else:
        name = args[args.index("--variant") + 1] if "--variant" in args else "ckb"
        setup, first, flag = VARIANTS[name]
        plan = [(f"variant {name}: take software control", p) for p in setup]
        if "--identify" in args:
            plan += [(f"zone {z} = #{color}", mouse_colors({z: rgb}, flag)) for z in range(first, first + 12)]
        elif "--zone" in args:
            z = int(args[args.index("--zone") + 1])
            plan.append((f"zone {z} = #{color}", mouse_colors({z: rgb}, flag)))
        else:
            plan.append((f"zones {first}-{first + 5} = #{color}", mouse_colors({z: rgb for z in range(first, first + 6)}, flag)))
    ch = ControlChannel() if send else None
    try:
        for label, pkt in plan:
            print(f"{label}\n  {pkt[:16].hex(' ')} ...")
            if ch:
                ch.send(pkt)
                if label.startswith("zone"):
                    time.sleep(2.0)
        if not send:
            print("\n(dry run: nothing sent; add --send to write to the mouse)")
    finally:
        if ch:
            ch.close()
    return 0
