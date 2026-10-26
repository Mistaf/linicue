"""The linicue daemon: window focus -> profile -> button actions + lighting on the Scimitar RGB Elite."""
from __future__ import annotations

import asyncio
import dataclasses
import signal
import sys
import time
from pathlib import Path
from typing import Callable

from . import lighting, mouse, nxp, store
from .dpi import Dpi, Preset, load_presets, manual_preset
from .link import MouseLink
from .player import Player, UInputSink
from .profile import Profile, ProfileSwitchAction, load_profiles
from .steam import SteamLibrary
from .switcher import Match, Overrides, RuleSet, Switcher, load_overrides, window_from_event

FRAME_SECONDS = 1 / 30
TEMP_REFRESH = 2.0
SETTLE = 0.25  # the mouse drops colour packets sent right after the mode switch
KEEPALIVE = 1.0  # resend an unchanged frame this often: a static profile is otherwise sent once and can be lost


class LogSink:
    """--dry-run output: shows what would be typed instead of typing it."""

    def __init__(self, log: Callable[[str], None]):
        self.log = log

    def key(self, code: int, down: bool) -> None:
        self.log(f"  key {code} {'down' if down else 'up'}")

    def rel(self, code: int, value: int) -> None:
        self.log(f"  rel {code} {value}")


class Daemon:
    def __init__(self, profiles: list[Profile], rules: RuleSet, sink, control: nxp.ControlChannel | None,
                 skip_leds: frozenset[str] = frozenset(), log: Callable[[str], None] = print, dpi: Dpi | None = None,
                 presets: dict[str, Preset] | None = None, dry: bool = False):
        self.profiles, self.control, self.skip, self.log, self.dpi = profiles, control, skip_leds, log, dpi
        self.presets, self.started = presets or {}, False
        self.dry = dry  # log what would be sent instead of writing to the mouse
        self.on_link_lost: Callable[[Exception], None] = lambda e: None  # set by MouseLink
        self.forced: Profile | None = None  # set by the GUI to preview a profile; window focus is ignored meanwhile
        self.player = Player(sink, on_switch=self.switch_profile, log=log,
                             on_dpi=dpi.handle if dpi else lambda fn, down: log("DPI button pressed but no DPI settings found (see README)"))
        self.switcher = Switcher(rules, self._apply)
        self.profile: Profile | None = None
        self.bindings: dict = {}
        self.layers: list = []
        self.t0 = time.monotonic()
        self.last_frame: dict | None = None
        self.sent_at = 0.0
        self.hold_until = 0.0
        self.temp, self.temp_at = None, 0.0
        if rules.default:
            self._apply(rules.default, None)

    # --- profile handling ----------------------------------------------------
    def _apply(self, profile: Profile, match: Match | None) -> None:
        self.player.release_all()  # never carry a held key or running macro into another profile
        if self.dpi:
            self.dpi.release()
            preset = self.presets.get(profile.mouse.dpi_ref)
            if preset and preset is not self.dpi.preset:  # profiles may point at different iCUE DPI presets
                self.dpi.configure(preset)
                if self.started:
                    self.dpi.setup()
        self.profile = profile
        self.switcher.current = profile
        self.bindings = {b.button: b for b in profile.mouse.bindings if b.button}
        self.layers = [dataclasses.replace(l, leds=tuple(x for x in l.leds if x not in self.skip))
                       for l in profile.mouse.lighting]
        self.t0, self.last_frame = time.monotonic(), None
        self.log(f"profile -> {profile.name}" + (f"  ({match.reason})" if match and match.score else ""))

    def on_window(self, resource_class: str, resource_name: str, desktop_file: str, caption: str, pid: int) -> None:
        if self.forced:
            return
        self.switcher.on_window(window_from_event(resource_class, resource_name, desktop_file, caption, pid))

    def force(self, profile_id: str) -> bool:
        """Pin a profile (GUI preview); an empty id releases the pin so window focus rules apply again."""
        if not profile_id:
            self.forced = None
            self.switcher.current = None
            return True
        target = next((p for p in self.profiles if p.id == profile_id), None)
        if target is None:
            return False
        self.forced = target
        if target is not self.profile:
            self._apply(target, None)
        return True

    def reload(self, profiles: list[Profile], rules: RuleSet, presets: dict[str, Preset]) -> None:
        """Swap in freshly loaded profiles (the GUI saved something); keep the profile in use if it still exists."""
        self.profiles, self.presets, self.switcher.rules = profiles, presets, rules
        keep = lambda pid: next((p for p in profiles if p.id == pid), None)
        self.forced = keep(self.forced.id) if self.forced else None
        target = self.forced or keep(self.profile.id if self.profile else "") or rules.default
        self.switcher.current = None
        if target:
            self._apply(target, None)

    def switch_profile(self, a: ProfileSwitchAction) -> None:
        by_id = {p.id: p for p in self.profiles}
        target = by_id.get(a.target)
        ids = [i for i in a.targets if i in by_id]
        if target is None and ids:  # cycle through the listed profiles
            step = -1 if a.direction == "Backward" else 1
            cur = ids.index(self.profile.id) if self.profile and self.profile.id in ids else -1
            target = by_id[ids[(cur + step) % len(ids)]]
        if target is None:
            self.log(f"profile switch: target {a.target or a.targets} not found")
        elif target is not self.profile:
            self._apply(target, None)

    # --- buttons ---------------------------------------------------------------
    def on_button(self, name: str, pressed: bool) -> None:
        b = self.bindings.get(name)
        if b is None:
            if name == "MouseDpiToggle" and pressed and self.dpi:  # iCUE's default for an unbound DPI button
                self.dpi.cycle()
            return
        try:
            self.player.button(name, b.action, pressed)
        except Exception as e:  # one bad binding must not kill the daemon
            self.log(f"{name}: {type(e).__name__}: {e}")

    def send(self, pkt: bytes) -> None:
        """Every write to the mouse goes through here: a vanished device is reported, never raised."""
        if self.control is None:
            if self.dry:
                self.log(f"  packet {pkt[:9].hex(' ')}")
            return
        try:
            self.control.send(pkt)
        except OSError as e:
            self.on_link_lost(e)

    # --- lighting ----------------------------------------------------------------
    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if now < self.hold_until:
            return
        if now - self.temp_at > TEMP_REFRESH:
            self.temp, self.temp_at = lighting.cpu_temp(), now
        frame = {z: (0, 0, 0) for z in lighting.ZONES.values()}  # unspecified zones are off
        frame.update(lighting.render(self.layers, (now - self.t0) * 1000, self.temp))
        if self.dpi and self.dpi.color():
            frame[lighting.ZONES["MouseDpiLed"]] = self.dpi.color()  # the DPI light shows the active stage
        changed = frame != self.last_frame
        if changed or now - self.sent_at > KEEPALIVE:
            self.last_frame, self.sent_at = frame, now
            if not self.dry:
                self.send(nxp.mouse_colors(frame))
            elif changed:
                self.log("  lights " + " ".join(f"{z}=#{r:02x}{g:02x}{b:02x}" for z, (r, g, b) in sorted(frame.items())))

    async def lighting_loop(self) -> None:
        while True:
            self.tick()
            await asyncio.sleep(FRAME_SECONDS)

    # --- lifecycle -----------------------------------------------------------------
    def start(self) -> None:
        self.started = True
        self.hold_until = time.monotonic() + SETTLE
        self.last_frame = None  # a (re)connected mouse has forgotten its colours
        self.send(nxp.special_mode(True))  # also stops the mouse handling DPI/sniper itself
        if self.dpi:
            self.dpi.setup()

    def stop(self) -> None:
        self.player.release_all()
        if self.dpi:
            self.dpi.release()
        self.send(nxp.special_mode(False))  # hand the mouse back to its own firmware, whatever happened
        self.send(nxp.lighting_control(False))


async def _guard(coro, log, what: str) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:  # e.g. no session bus: keep running without window tracking
        log(f"{what} stopped: {type(e).__name__}: {e}")


def _source(args: list[str], overrides: Overrides):
    """-> (rebuild, watch_root). rebuild() loads profiles + DPI presets from iCUE files (a folder argument) or our store."""
    folder = args[0] if args and not args[0].startswith("--") else None
    steam = SteamLibrary.discover(extra_libraries=overrides.steam_libraries)

    def rebuild():
        if folder:
            profiles = load_profiles(folder)
            library = Path(overrides.dpi_library).expanduser() if overrides.dpi_library else Path(folder).resolve().parent / "dpi" / "dpi.cuelibrary"
            presets = load_presets(library) if library.is_file() else {}
        else:
            profiles, presets = store.load_store()
        if overrides.dpi_stages:  # rules.toml values win over the stored/iCUE presets
            colors = [tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) for c in overrides.dpi_colors]
            presets = {p.mouse.dpi_ref: manual_preset(list(overrides.dpi_stages), overrides.dpi_sniper, overrides.dpi_start, colors)
                       for p in profiles if p.mouse}
        return profiles, RuleSet(profiles, steam, overrides), presets

    return rebuild, (None if folder else store.CONFIG_DIR)


async def _watch_store(d: Daemon, rebuild, root: Path, log) -> None:
    last = store.stamp(root)
    while True:
        await asyncio.sleep(1)
        now = store.stamp(root)
        if now != last:
            last = now
            try:
                d.reload(*rebuild())
                log("profiles reloaded")
            except Exception as e:  # a half-edited file must not stop the daemon
                log(f"reload failed, keeping the old profiles: {type(e).__name__}: {e}")


async def run(args: list[str]) -> int:
    dry = "--dry-run" in args
    cfg = Path(args[args.index("--config") + 1]) if "--config" in args else store.CONFIG_DIR / "rules.toml"
    overrides = load_overrides(cfg) if cfg.is_file() else Overrides()
    rebuild, watch_root = _source(args, overrides)
    profiles, rules, presets = rebuild()
    if not profiles:
        print("no profiles: run `python -m linicue import <iCUE profiles folder>` first, or pass that folder to `run`", file=sys.stderr)
        return 1
    log = lambda m: print(time.strftime("%H:%M:%S"), m, flush=True)

    d: Daemon | None = None
    dpi = Dpi(lambda pkt: d.send(pkt))  # late-bound: d is created just below
    if not presets:
        dpi = None
        log("no DPI settings found: DPI and Sniper buttons do nothing (see README)")
    d = Daemon(profiles, rules, LogSink(log) if dry else UInputSink(), None, overrides.skip_leds, log, dpi, presets, dry)
    if dpi and dpi.preset is None:  # the starting profile may not name a preset: use the first one
        dpi.configure(next(iter(presets.values())))
    if "--profile" in args:
        if not d.force(next((p.id for p in profiles if p.name.lower() == args[args.index("--profile") + 1].lower()), "")):
            print("no such profile", file=sys.stderr)
            return 1
    for exe, names in rules.ambiguities().items():
        log(f"paired profiles on {exe}: {', '.join(names)} (switch with the profile-switch button)")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    link = MouseLink(d, log, dry)
    tasks = [asyncio.create_task(d.lighting_loop()), asyncio.create_task(link.run())]
    if watch_root:
        tasks.append(asyncio.create_task(_watch_store(d, rebuild, watch_root, log)))
    if "--no-dbus" not in args:
        try:
            from .dbus_service import serve, watch_sleep
            tasks.append(asyncio.create_task(_guard(serve(d, rebuild), log, "window tracking (D-Bus)")))
            tasks.append(asyncio.create_task(_guard(watch_sleep(link.resumed), log, "suspend/resume watch")))
        except ImportError:
            log("dbus-next not installed: window-based profile switching is off (pip install dbus-next)")
    log("running; Ctrl-C to stop" + ("  [dry run: no writes to the mouse, no key output]" if dry else ""))
    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        d.stop()  # hands the mouse back to its firmware while the channel is still open
        link.lost("shutting down")
        if hasattr(d.player.sink, "close"):
            d.player.sink.close()
    return 0
