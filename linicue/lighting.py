"""Render a profile's mouse lighting layers into per-zone colours."""
from __future__ import annotations

import glob
import time
from pathlib import Path

from .profile import MOUSE_LEDS, Color, Effect, LightingLayer

# Zone order verified on a Scimitar RGB Elite with `lights --identify` (zone 3, by the buttons, is probably the DPI light).
ZONES = {led: i + 1 for i, led in enumerate(MOUSE_LEDS)}
RGB = tuple[int, int, int]


def _lerp(stops: list[tuple[float, Color]], x: float) -> Color:
    if x <= stops[0][0]:
        return stops[0][1]
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x <= x1:
            f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return Color(*(a + (b - a) * f for a, b in zip((c0.r, c0.g, c0.b), (c1.r, c1.g, c1.b))))
    return stops[-1][1]


def effect_color(e: Effect, t_ms: float, temp_c: float | None) -> RGB | None:
    """None when the effect type is not supported yet."""
    if not e.stops:
        return None
    if e.kind in ("StaticLighting", "SolidLighting"):
        c = e.stops[0][1]
    elif e.kind == "GradientLighting":
        # shortcut: stops are interpolated in RGB over one loop of `duration`; stop times are 0..1
        c = _lerp(e.stops, (t_ms % e.duration_ms) / e.duration_ms if e.duration_ms else 0.0)
    elif e.kind == "TemperatureLighting":
        c = _lerp(e.stops, temp_c if temp_c is not None else e.stops[0][0])
    else:
        return None
    k = max(0, min(10, e.brightness)) / 10  # shortcut: iCUE brightness 0-10 taken as a linear scale
    return tuple(round(v * 255 * k) for v in (c.r, c.g, c.b))  # type: ignore[return-value]


def render(layers: list[LightingLayer], t_ms: float, temp_c: float | None = None) -> dict[int, RGB]:
    """Zone -> colour. The first layer in the list is on top (assumed from how iCUE profiles read)."""
    frame: dict[int, RGB] = {}
    for layer in reversed(layers):
        if not layer.enabled or layer.effect is None:
            continue
        col = effect_color(layer.effect, t_ms, temp_c)
        if col is None:
            continue
        for led in layer.leds:
            if led in ZONES:
                frame[ZONES[led]] = col
    return frame


def cpu_temp() -> float | None:
    """Stand-in for iCUE's sensor: hottest CPU hwmon reading, in Celsius."""
    best = None
    for name_file in glob.glob("/sys/class/hwmon/hwmon*/name"):
        d = Path(name_file).parent
        if d.joinpath("name").read_text().strip() not in ("k10temp", "coretemp", "zenpower"):
            continue
        for f in d.glob("temp*_input"):
            try:
                v = int(f.read_text()) / 1000
            except (OSError, ValueError):
                continue
            best = v if best is None else max(best, v)
    return best


def preview_cli(args: list[str]) -> int:
    """python -m linicue preview <profile-dir> <name> [--send] [--seconds N]"""
    from . import nxp
    from .profile import load_profiles

    profiles = [p for p in load_profiles(args[0]) if p.name.lower() == args[1].lower()]
    if not profiles:
        print(f"no profile named {args[1]!r}")
        return 1
    layers = profiles[0].mouse.lighting
    seconds = float(args[args.index("--seconds") + 1]) if "--seconds" in args else 30.0
    unsupported = {l.effect.kind for l in layers if l.effect and effect_color(l.effect, 0, 0) is None}
    if unsupported:
        print("not rendered yet:", ", ".join(sorted(unsupported)))
    if "--send" not in args:
        for t in (0, 2500, 5000):
            print(f"t={t:>5}ms", {z: "#%02x%02x%02x" % c for z, c in sorted(render(layers, t, cpu_temp()).items())})
        print("(dry run: add --send to play it on the mouse; Ctrl-C stops and restores)")
        return 0
    ch = nxp.ControlChannel()
    try:
        ch.send(nxp.special_mode(True))
        start, last = time.monotonic(), None
        while time.monotonic() - start < seconds:
            frame = render(layers, (time.monotonic() - start) * 1000, cpu_temp())
            if frame != last and frame:
                ch.send(nxp.mouse_colors(frame))
                last = frame
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        ch.send(nxp.special_mode(False))
        ch.send(nxp.lighting_control(False))
        ch.close()
    return 0
