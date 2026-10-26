"""linicue's own profile storage (JSON in ~/.config/linicue) and the one-time import from iCUE files."""
from __future__ import annotations

import json
import ntpath
import os
import re
from dataclasses import asdict, fields
from pathlib import Path

from .dpi import Preset, load_icue_presets, to_preset
from .steam import installdir_from_path
from .profile import (Action, Binding, Color, Effect, ExecHints, KeyRemapAction, LaunchAction, LightingLayer,
                      MacroAction, MacroEvent, MediaAction, MouseSettings, Profile, ProfileSwitchAction,
                      RepeatOptions, TextAction, load_profiles)

VERSION = 1
CONFIG_DIR = Path(os.environ.get("LINICUE_CONFIG", "~/.config/linicue")).expanduser()
# keyed by Action.type, which keeps iCUE's names (they differ from our class names for the last two)
_ACTIONS = {"MacroAction": MacroAction, "KeyRemapAction": KeyRemapAction, "TextAction": TextAction, "MediaAction": MediaAction,
            "LaunchApplicationAction": LaunchAction, "ProfileSwitchingAction": ProfileSwitchAction}


# --- actions -------------------------------------------------------------------

def action_to_dict(a: Action | None) -> dict | None:
    if a is None:
        return None
    d = {f.name: getattr(a, f.name) for f in fields(a) if f.name != "raw"}
    d["repeat"], d["hints"] = asdict(a.repeat), asdict(a.hints)
    if isinstance(a, MacroAction):
        d["events"] = [asdict(e) for e in a.events]
    return d


def action_from_dict(d: dict | None) -> Action | None:
    if d is None:
        return None
    cls = _ACTIONS.get(d["type"], Action)
    kw = {f.name: d[f.name] for f in fields(cls) if f.name != "raw" and f.name in d}
    kw["repeat"] = RepeatOptions(**{**d["repeat"], "random_delay": tuple(d["repeat"]["random_delay"])})
    kw["hints"] = ExecHints(**d["hints"])
    for k in ("keystroke", "targets"):
        if k in kw:
            kw[k] = tuple(kw[k])
    if cls is MacroAction:
        kw["events"] = [MacroEvent(**{**e, "keys": tuple(e["keys"])}) for e in d["events"]]
    return cls(**kw)


# --- lighting ------------------------------------------------------------------

def _color(c: Color) -> list[float]:
    return [c.r, c.g, c.b]


def effect_to_dict(e: Effect | None) -> dict | None:
    if e is None:
        return None
    return {"kind": e.kind, "duration_ms": e.duration_ms, "brightness": e.brightness,
            "stops": [[t, *_color(c)] for t, c in e.stops], "params": e.params}


def effect_from_dict(d: dict | None) -> Effect | None:
    if d is None:
        return None
    return Effect(d["kind"], d["duration_ms"], d["brightness"], [(t, Color(r, g, b)) for t, r, g, b in d["stops"]], d.get("params", {}))


# --- profiles ------------------------------------------------------------------

def profile_to_dict(p: Profile) -> dict:
    m = p.mouse
    return {
        "version": VERSION, "id": p.id, "name": p.name, "linked_programs": p.linked_programs, "is_initial": p.is_initial,
        "mouse": None if m is None else {
            "dpi_ref": m.dpi_ref, "angle_snapping": m.angle_snapping, "angle_snapping_value": m.angle_snapping_value,
            "bindings": [{"button": b.button, "layer": b.layer, "event": b.event, "action": action_to_dict(b.action)} for b in m.bindings],
            "lighting": [{"name": l.name, "id": l.id, "leds": list(l.leds), "enabled": l.enabled, "plays": l.plays,
                          "start_with_profile": l.start_with_profile, "effect": effect_to_dict(l.effect)} for l in m.lighting],
        },
    }


def profile_from_dict(d: dict, path: Path | None = None) -> Profile:
    mouse = None
    if d.get("mouse") is not None:
        m = d["mouse"]
        mouse = MouseSettings(
            [Binding(b["button"], action_from_dict(b["action"]), b.get("layer", "StandardLayer"), b.get("event", "Click")) for b in m["bindings"]],
            [LightingLayer(l["name"], l["id"], tuple(l["leds"]), l["enabled"], effect_from_dict(l["effect"]), l.get("plays", "Standard"),
                           l.get("start_with_profile", True)) for l in m["lighting"]],
            m.get("angle_snapping", False), m.get("angle_snapping_value", 0), m.get("dpi_ref", ""))
    return Profile(d["id"], d["name"], list(d["linked_programs"]), mouse, path, bool(d.get("is_initial")))


def _write_atomic(path: Path, data: dict) -> None:
    """Write-then-rename so the daemon (which polls this folder) never reads half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str))
    os.replace(tmp, path)


def _filename(profile_id: str) -> str:
    return re.sub(r"[^0-9a-zA-Z-]", "", profile_id) + ".json"


def save_profile(p: Profile, root: Path = CONFIG_DIR) -> Path:
    path = root / "profiles" / _filename(p.id)
    _write_atomic(path, profile_to_dict(p))
    p.path = path
    return path


def delete_profile(p: Profile, root: Path = CONFIG_DIR) -> None:
    (root / "profiles" / _filename(p.id)).unlink(missing_ok=True)


def save_presets(presets: dict[str, dict], root: Path = CONFIG_DIR) -> None:
    _write_atomic(root / "dpi.json", {"version": VERSION, "presets": presets})


def load_raw_presets(root: Path = CONFIG_DIR) -> dict[str, dict]:
    f = root / "dpi.json"
    return json.loads(f.read_text())["presets"] if f.is_file() else {}


def load_settings(root: Path = CONFIG_DIR) -> dict:
    """Device-wide settings (not per profile), e.g. {"polling_rate_hz": 1000}; missing file = nothing chosen."""
    f = root / "settings.json"
    return {k: v for k, v in json.loads(f.read_text()).items() if k != "version"} if f.is_file() else {}


def save_settings(settings: dict, root: Path = CONFIG_DIR) -> None:
    _write_atomic(root / "settings.json", {"version": VERSION, **settings})


def load_store(root: Path = CONFIG_DIR) -> tuple[list[Profile], dict[str, Preset]]:
    profiles = []
    for f in sorted((root / "profiles").glob("*.json")):
        profiles.append(profile_from_dict(json.loads(f.read_text()), f))
    return profiles, {i: to_preset(r) for i, r in load_raw_presets(root).items()}


def stamp(root: Path = CONFIG_DIR) -> float:
    """Newest modification time in the store: the daemon reloads when this changes."""
    files = [*(root / "profiles").glob("*.json"), root / "dpi.json", root / "settings.json"]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)


def dedupe_programs(paths: list[str]) -> list[str]:
    """iCUE lists one path per installed version (Discord had 55); keep one per program and Steam install folder."""
    seen: dict[tuple[str, str], str] = {}
    for path in paths:
        key = (ntpath.basename(path.replace("/", "\\")).lower(), installdir_from_path(path) or "")
        seen.setdefault(key, path)
    return list(seen.values())


def import_icue(profile_dir: str | Path, root: Path = CONFIG_DIR, dpi_library: str | Path | None = None) -> int:
    """Copy software profiles (and the DPI presets) out of iCUE's files; returns the number of profiles."""
    n = 0
    for p in load_profiles(profile_dir):
        if p.is_hardware or p.mouse is None:
            continue
        p.linked_programs = dedupe_programs(p.linked_programs)
        save_profile(p, root)
        n += 1
    lib = Path(dpi_library) if dpi_library else Path(profile_dir).resolve().parent / "dpi" / "dpi.cuelibrary"
    if lib.is_file():
        save_presets(load_icue_presets(lib), root)
    return n
