"""DPI stages and the sniper button. In software mode the host switches stages; the mouse no longer does."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import cereal, nxp
from .keys import DPI_DOWN, DPI_UP, SNIPER
from .profile import Color

Stage = tuple[int, int, "tuple[int, int, int] | None"]  # dpi x, dpi y, DPI light colour


@dataclass
class Preset:
    """Enabled stages by number (1..5) plus the sniper stage (always stage 0 on the wire)."""
    stages: dict[int, Stage] = field(default_factory=dict)
    sniper: Stage | None = None
    default: int = 1


def load_icue_presets(path: str | Path, model: str = "SCIMITAR RGB ELITE") -> dict[str, dict]:
    """iCUE's dpi.cuelibrary as plain JSON-ready dicts (all stages, enabled or not):
    id -> {"name", "default", "stages": {"1".."5": stage}, "sniper": stage}, stage = {"dpi": [x, y], "enabled", "color": [r, g, b]}."""
    out: dict[str, dict] = {}
    for entry in cereal.load(str(path))["value0"]:
        if entry["key"] != model:
            continue
        for p in entry["value"]:
            pre = {"name": str(p.get("name", "")), "default": int(str(p.get("defaultIndex", "Dpi1"))[3:]), "stages": {}}
            for kv in p["settings"]:
                v = kv["value"]
                st = {"dpi": [int(v["dpiX"]), int(v["dpiY"])], "enabled": bool(v["enabled"]), "color": list(Color.parse(v["color"]).rgb8())}
                if kv["key"] == "SniperDpi":
                    pre["sniper"] = st
                else:
                    pre["stages"][kv["key"][3:]] = st
            out[p["id"]] = pre
    return out


def to_preset(raw: dict) -> Preset:
    """Runtime preset (enabled stages only) from the stored/JSON form."""
    stage = lambda s: (s["dpi"][0], s["dpi"][1], tuple(s["color"]))
    sn = raw.get("sniper")
    return Preset({int(i): stage(s) for i, s in raw["stages"].items() if s["enabled"]},
                  stage(sn) if sn and sn["enabled"] else None, int(raw.get("default", 1)))


def load_presets(path: str | Path, model: str = "SCIMITAR RGB ELITE") -> dict[str, Preset]:
    return {i: to_preset(r) for i, r in load_icue_presets(path, model).items()}


def manual_preset(stages: list[int], sniper: int | None, start: int, colors: list[tuple[int, int, int]]) -> Preset:
    """Build a preset from rules.toml values; colors: sniper first, then one per stage."""
    col = lambda i: colors[i] if i < len(colors) else None
    return Preset({i + 1: (d, d, col(i + 1)) for i, d in enumerate(stages)},
                  (sniper, sniper, col(0)) if sniper else None, start)


class Dpi:
    def __init__(self, send: Callable[[bytes], None], preset: Preset | None = None):
        self.send = send
        self.preset: Preset | None = None
        self.cur, self.sniping = 1, False
        if preset:
            self.configure(preset)

    def configure(self, preset: Preset) -> None:
        if not preset.stages:
            raise ValueError("a DPI preset needs at least one enabled stage")
        self.preset, self.sniping = preset, False
        self.cur = preset.default if preset.default in preset.stages else min(preset.stages)

    @property
    def active_stage(self) -> int:
        return 0 if self.sniping else self.cur

    def color(self) -> tuple[int, int, int] | None:
        """Colour for the DPI light of the active stage."""
        if not self.preset:
            return None
        stage = self.preset.sniper if self.sniping else self.preset.stages[self.cur]
        return stage[2] if stage else None

    def setup(self) -> None:
        p = self.preset
        wire = {i: s for i, s in p.stages.items()}
        if p.sniper:
            wire[0] = p.sniper
        for i, (x, y, _) in sorted(wire.items()):
            self.send(nxp.dpi_stage(i, x, y))
        self.send(nxp.dpi_mask(set(wire)))
        self.send(nxp.dpi_select(self.cur))

    def _step(self, delta: int, wrap: bool) -> None:
        order = sorted(self.preset.stages)
        i = order.index(self.cur) + delta
        self.cur = order[i % len(order)] if wrap else order[min(max(i, 0), len(order) - 1)]
        self.send(nxp.dpi_select(self.active_stage))

    def cycle(self) -> None:
        """The DPI button's default action: next enabled stage, wrapping."""
        if self.preset:
            self._step(1, True)

    def handle(self, fn: int, down: bool) -> None:
        if not self.preset:
            return
        if fn == SNIPER:
            if not self.preset.sniper:
                return
            self.sniping = down
            self.send(nxp.dpi_select(self.active_stage))
        elif down and fn in (DPI_UP, DPI_DOWN):
            self._step(1 if fn == DPI_UP else -1, False)

    def release(self) -> None:
        """Drop the sniper stage (profile change / shutdown) so DPI is never left low."""
        if self.sniping:
            self.handle(SNIPER, False)
