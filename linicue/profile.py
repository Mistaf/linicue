"""Typed view of iCUE ``.cueprofiledata`` files, focused on the Scimitar mouse."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import cereal

MOUSE_KEY = "Mouse"
MOUSE_LEDS = ("MouseFrontLed", "MouseLogoLed", "MouseDpiLed", "MouseScrollLed", "MouseSideLed")
LIGHTING_CAPS = "StandardRgb"  # the entry that holds the profile's own layers; the other entries are unused placeholders
_COLOR_RE = re.compile(r"rgba?\(([^)]*)\)")
_GUID_RE = re.compile(r"^\{[0-9a-fA-F-]{36}\}$")


def _s(v: Any) -> str:
    """Names such as the digit key "1" decode as ints; turn them back."""
    return "" if v is None or v == "" else str(v)


@dataclass(frozen=True)
class Color:
    r: float
    g: float
    b: float
    a: float = 1.0

    @classmethod
    def parse(cls, text: str) -> "Color":
        m = _COLOR_RE.match(str(text).strip())
        if not m:
            raise ValueError(f"unrecognised colour {text!r}")
        parts = [float(p) for p in m.group(1).replace(",", " ").split()]
        return cls(*parts[:4])

    def rgb8(self) -> tuple[int, int, int]:
        return tuple(round(max(0.0, min(1.0, c)) * 255) for c in (self.r, self.g, self.b))  # type: ignore[return-value]


# --- actions -----------------------------------------------------------------

@dataclass
class RepeatOptions:
    mode: str = "NoRepeat"
    count: int = 1
    delay: int = 0
    delay_mode: str = "Constant"
    random_delay: tuple[int, int] = (0, 0)


@dataclass
class ExecHints:
    when: str = "OnPress"  # OnPress | OnBoth | Toggle | WhilePressed
    terminate_on_second_exec: bool = False
    restart_on_second_exec: bool = False
    retain_original_key_output: bool = False


@dataclass
class Action:
    type: str
    name: str
    id: str
    repeat: RepeatOptions
    hints: ExecHints
    raw: dict = field(repr=False, default_factory=dict)


@dataclass
class MacroEvent:
    kind: str  # key | delay | mouse
    keys: tuple[str, ...] = ()
    pressed: bool = True
    delay_ms: int = 0
    delay_max_ms: int | None = None  # set when the delay is random in [delay_ms, delay_max_ms]
    button: int = 0


@dataclass
class MacroAction(Action):
    events: list[MacroEvent] = field(default_factory=list)
    termination: str = "Interrupt"
    high_priority: bool = False


@dataclass
class KeyRemapAction(Action):
    key: str = ""
    keystroke: tuple[str, ...] = ()


@dataclass
class TextAction(Action):
    text: str = ""
    char_delay_ms: int = 0


@dataclass
class MediaAction(Action):
    media: str = ""


@dataclass
class LaunchAction(Action):
    path: str = ""
    url: str = ""
    predefined: int = 0


@dataclass
class ProfileSwitchAction(Action):
    switch_type: str = ""
    target: str = ""
    targets: tuple[str, ...] = ()
    direction: str = ""
    loop: bool = False


@dataclass
class Binding:
    button: str
    action: Action | None
    layer: str = "StandardLayer"
    event: str = "Click"


def _repeat(base: dict) -> RepeatOptions:
    r = base.get("repeatOptions") or {}
    return RepeatOptions(
        _s(r.get("repeatMode")) or "NoRepeat", r.get("repeatCount", 1), r.get("delay", 0),
        _s(r.get("delayMode")) or "Constant", (r.get("randomDelayFrom", 0), r.get("randomDelayTo", 0)),
    )


def _hints(base: dict) -> ExecHints:
    h = base.get("executionHints") or {}
    return ExecHints(
        _s(h.get("execHint")) or "OnPress", bool(h.get("terminateOnSecondExec")),
        bool(h.get("restartOnSecondExec")), bool(h.get("retainOriginalKeyOutput")),
    )


def _macro_event(ev: dict) -> MacroEvent:
    t = ev.type
    if t == "KeyboardMacroActionEvent":
        return MacroEvent("key", tuple(_s(k) for k in ev["keys"]), pressed=ev["sub"] == "KeyPress")
    if t == "DelayMacroActionEvent":
        if ev.get("useRandom"):
            return MacroEvent("delay", delay_ms=int(ev["delayMin"]), delay_max_ms=int(ev["delayMax"]))
        return MacroEvent("delay", delay_ms=int(ev["delay"]))
    if t == "MouseButtonMacroActionEvent":
        return MacroEvent("mouse", pressed=ev["sub"] == "ButtonPress", button=int(ev["button"]))
    raise ValueError(f"unknown macro event {t!r}")


def parse_action(a: cereal.Node | None) -> Action | None:
    if a is None:
        return None
    common = dict(type=a.type or "", name=_s(a.get("name")), id=_s(a.get("id")),
                  repeat=_repeat(a), hints=_hints(a), raw=a)
    t = a.type
    if t == "MacroAction":
        return MacroAction(**common, events=[_macro_event(e) for e in a["events"]],
                           termination=_s(a.get("terminationMethod")), high_priority=bool(a.get("highPriority")))
    if t == "KeyRemapAction":
        return KeyRemapAction(**common, key=_s(a.get("keyName")), keystroke=tuple(_s(k) for k in a.get("keyStroke") or []))
    if t == "TextAction":
        return TextAction(**common, text=_s(a.get("text")), char_delay_ms=int(a.get("delayBetweenCharacters") or 0))
    if t == "MediaAction":
        return MediaAction(**common, media=_s(a.get("action")))
    if t == "LaunchApplicationAction":
        return LaunchAction(**common, path=_s(a.get("applicationPath")), url=_s(a.get("webUrl")),
                            predefined=int(a.get("predefinedAction") or 0))
    if t == "ProfileSwitchingAction":
        return ProfileSwitchAction(**common, switch_type=_s(a.get("switchType")), target=_s(a.get("profile")),
                                   targets=tuple(a.get("profiles") or ()), direction=_s(a.get("direction")),
                                   loop=bool(a.get("loop")))
    return Action(**common)


# --- lighting ----------------------------------------------------------------

@dataclass
class Effect:
    kind: str  # e.g. GradientLighting, StaticLighting, RainbowLighting
    duration_ms: int
    brightness: int
    stops: list[tuple[float, Color]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class LightingLayer:
    name: str
    id: str
    leds: tuple[str, ...]
    enabled: bool
    effect: Effect | None
    plays: str = "Standard"
    start_with_profile: bool = True


def _effect(n: Any) -> Effect | None:
    """Unwrap LightingLink/Temperature wrappers and normalise colour stops."""
    while isinstance(n, dict) and n.type == "LightingLink":
        n = (n.get("layer") or {}).get("lighting")
    if not isinstance(n, dict) or n.type is None:
        return None
    src = n
    if isinstance(n.get("value0"), dict):  # base class written as value0 (SingleColorWaveLighting)
        src = {**n["value0"], **{k: v for k, v in n.items() if k != "value0"}}
    params = {k: v for k, v in src.items() if k not in ("name", "duration", "brightness", "transitions", "value0", "impl", "color1", "color2")}
    stops = [(float(t["time"]), Color.parse(t["color"])) for t in src.get("transitions") or []]
    if "color1" in src:  # BlinkLighting
        stops = [(0.0, Color.parse(src["color1"])), (1.0, Color.parse(src["color2"]))]
    if n.type == "TemperatureLighting" and isinstance(src.get("impl"), dict):
        impl = src["impl"]
        params["sensor"] = impl.get("sensorId")
        stops = [(float(t["time"]), Color.parse(t["color"])) for t in impl.get("transitions") or []]
    return Effect(n.type, int(src.get("duration", 0)), int(src.get("brightness", 0)), stops, params)


def _layer(n: cereal.Node) -> LightingLayer:
    h = n.get("executionHints") or {}
    keys = tuple(_s(k) for k in n.get("keys") or [])
    if n.get("option") == "AllLeds":  # empty key list means "every LED of the device"
        keys = MOUSE_LEDS
    return LightingLayer(
        _s(n.get("name")), _s(n.get("id")), keys,
        bool(n.get("enabled", True)), _effect(n.get("lighting")),
        _s(h.get("playOption")) or "Standard", bool(h.get("startWithProfile", True)),
    )


# --- profile -----------------------------------------------------------------

@dataclass
class MouseSettings:
    bindings: list[Binding] = field(default_factory=list)
    lighting: list[LightingLayer] = field(default_factory=list)
    angle_snapping: bool = False
    angle_snapping_value: int = 0
    dpi_ref: str = ""  # GUID; stage values are not stored in the profile files
    indicator_colors: dict[str, Color] = field(default_factory=dict)

    def binding(self, button: str) -> Binding | None:
        return next((b for b in self.bindings if b.button == button), None)


@dataclass
class Profile:
    id: str
    name: str
    linked_programs: list[str]
    mouse: MouseSettings | None
    path: Path | None = None
    is_initial: bool = False  # iCUE's fallback profile when no linked program has focus

    @property
    def is_hardware(self) -> bool:
        return self.id.startswith("{008b1b00-")


def _mouse(props: list) -> MouseSettings:
    m = MouseSettings()
    seen_layers: set[str] = set()
    for prop in props:
        t = prop.type
        if t == "ActionsProperty::Proxy":
            for ent in prop["properties"]:
                for pair in ent["value"]["actions"]:
                    s = pair["second"]
                    m.bindings.append(Binding(_s(s.get("key")), parse_action(pair["first"]),
                                              _s(s.get("layer")), _s(s.get("event"))))
        elif t == "AggregatedLightingsProperty::Proxy":
            for ent in prop["properties"]:
                if _s(ent["key"].get("hidCaps")) != LIGHTING_CAPS:
                    continue
                for ch in ent["value"]["channelProperties"]:
                    for group in ch["value"]:
                        for ln in group["layers"]:
                            lay = _layer(ln)
                            if lay.id in seen_layers or not any(k.startswith("Mouse") for k in lay.leds):
                                continue
                            seen_layers.add(lay.id)
                            m.lighting.append(lay)
        elif t == "AngleSnappingProperty":
            m.angle_snapping, m.angle_snapping_value = bool(prop["enabled"]), int(prop["value"])
        elif t == "DPIProperty::Proxy":
            for ent in prop["properties"]:
                m.dpi_ref = _s((ent["value"] or {}).get("id"))
        elif t == "ProfileIndicatorProperty":
            for k in ("m1Color", "m2Color", "m3Color"):
                if isinstance(prop.get(k), str):
                    m.indicator_colors[k[:2]] = Color.parse(prop[k])
    return m


def load_profile(path: str | Path) -> Profile:
    raw = cereal.load(str(path))["profile"]
    mouse_entry = next((e["value"] for e in raw["properties"] if e["key"] == MOUSE_KEY), None)
    seen: dict[str, None] = {}
    for p in raw.get("linkedProgramsPaths") or []:
        seen.setdefault(_s(p), None)
    return Profile(_s(raw["id"]), _s(raw["name"]), list(seen),
                   _mouse(mouse_entry["properties"]) if mouse_entry else None, Path(path),
                   bool(raw.get("isInitial")))


def load_profiles(directory: str | Path) -> list[Profile]:
    """Load every ``{guid}.cueprofiledata`` (ignores iCUE's random-suffix temp copies)."""
    files = sorted(Path(directory).glob("*.cueprofiledata"))
    return [load_profile(f) for f in files]
