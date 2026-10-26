"""Pick the iCUE profile for the focused window.

Rules are derived from each profile's linked Windows program paths:
  * a Steam install dir resolves to an app ID (Proton windows are ``steam_app_<id>``),
  * the exe name is compared with the Wine process's exe or, for native apps, with the
    window class / desktop file / process name.
A ``rules.toml`` can add classes, title regexes or ignored classes (see ``load_overrides``).
"""
from __future__ import annotations

import ntpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .profile import Profile
from .steam import SteamLibrary, installdir_from_path

SCORE_APPID = 100
SCORE_CONFIG_CLASS = 90
SCORE_WINE_EXE = 80
SCORE_NATIVE_EXE = 70
SCORE_ALIAS = 50

# Windows exe stems that run under a different name on Linux.
EXE_ALIASES = {"javaw": {"java"}}  # the same program under its Linux name; other programs are added by the user as app links
# Windows/shell surfaces that briefly take focus and should not change the profile.
DEFAULT_IGNORED = frozenset({"plasmashell", "krunner", "kwin_wayland", "kwin_x11", "org.kde.plasmashell",
                             "ksmserver-logout-greeter", "xdg-desktop-portal-kde", "org.kde.spectacle"})

_STEAM_CLASS = re.compile(r"^steam_app_(\d+)$")


def norm(s: str) -> str:
    """Compare names loosely: lower-case, no ``.exe``, only alphanumerics."""
    s = s.lower()
    if s.endswith(".exe"):
        s = s[:-4]
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass
class WindowInfo:
    resource_class: str = ""
    resource_name: str = ""
    desktop_file: str = ""
    caption: str = ""
    pid: int = 0
    exe_names: tuple[str, ...] = ()  # native process name(s)
    wine_exes: tuple[str, ...] = ()  # Windows exe basenames seen in the process command line
    steam_appid: int | None = None

    def names(self) -> set[str]:
        out = {self.resource_class, self.resource_name, self.desktop_file, *self.exe_names}
        if self.desktop_file:
            out.add(self.desktop_file.rsplit(".", 1)[-1])
        return {norm(n) for n in out if n}


def inspect_process(pid: int, proc_root: str | Path = "/proc") -> dict:
    """Read what we can about *pid* (same-user processes only); never raises."""
    root = Path(proc_root) / str(pid)
    info: dict = {"exe_names": (), "wine_exes": (), "steam_appid": None}
    try:
        argv = [a for a in (root / "cmdline").read_bytes().decode("utf-8", "replace").split("\0") if a]
    except OSError:
        argv = []
    names: list[str] = []
    try:
        names.append(Path(str((root / "exe").readlink())).name)
    except OSError:
        pass
    if argv:
        names.append(Path(argv[0]).name)
    wine = [ntpath.basename(a.replace("/", "\\")) for a in argv if a.lower().endswith(".exe")]
    info["exe_names"] = tuple(dict.fromkeys(n for n in names if n))
    info["wine_exes"] = tuple(dict.fromkeys(wine))
    try:
        env = dict(kv.split("=", 1) for kv in (root / "environ").read_bytes().decode("utf-8", "replace").split("\0") if "=" in kv)
        for k in ("SteamAppId", "SteamGameId"):
            if env.get(k, "").isdigit() and env[k] != "0":
                info["steam_appid"] = int(env[k])
                break
    except OSError:
        pass
    return info


def window_from_event(resource_class: str, resource_name: str, desktop_file: str, caption: str, pid: int,
                      proc_root: str | Path = "/proc") -> WindowInfo:
    w = WindowInfo(resource_class, resource_name, desktop_file, caption, pid)
    if pid:
        p = inspect_process(pid, proc_root)
        w.exe_names, w.wine_exes, w.steam_appid = p["exe_names"], p["wine_exes"], p["steam_appid"]
    m = _STEAM_CLASS.match(resource_class)
    if m:
        w.steam_appid = int(m.group(1))
    return w


@dataclass
class Rule:
    profile: Profile
    exes: set[str] = field(default_factory=set)  # lower-case basenames, e.g. "discord.exe"
    appids: set[int] = field(default_factory=set)
    installdirs: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)  # normalised extra names from rules.toml
    title: re.Pattern | None = None

    def score(self, w: WindowInfo) -> tuple[int, str]:
        if self.title and not self.title.search(w.caption):
            return 0, ""
        best, why = 0, ""

        def hit(score: int, reason: str) -> None:
            nonlocal best, why
            if score > best:
                best, why = score, reason

        if w.steam_appid is not None and w.steam_appid in self.appids:
            hit(SCORE_APPID, "steam app id")
        names = w.names()
        if self.classes & names:
            hit(SCORE_CONFIG_CLASS, "configured class")
        if {e.lower() for e in w.wine_exes} & self.exes:
            hit(SCORE_WINE_EXE, "wine exe")
        stems = {norm(e) for e in self.exes}
        if stems & {norm(e) for e in w.exe_names}:
            hit(SCORE_NATIVE_EXE, "native process")
        aliases = set(stems)
        for stem in stems:
            aliases |= EXE_ALIASES.get(stem, set())
        if aliases & names:
            hit(SCORE_ALIAS, "window class/desktop file")
        if best and self.title:
            best, why = best + 5, why + " + title"
        return best, why


@dataclass
class Match:
    profile: Profile | None
    score: int = 0
    reason: str = ""
    ties: list[Profile] = field(default_factory=list)  # other profiles with the same top score


@dataclass
class Overrides:
    ignored: frozenset[str] = DEFAULT_IGNORED
    classes: dict[str, set[str]] = field(default_factory=dict)  # profile name -> classes
    titles: dict[str, str] = field(default_factory=dict)  # profile name -> regex
    steam_libraries: tuple[str, ...] = ()
    skip_leds: frozenset[str] = frozenset()  # e.g. MouseDpiLed: never lit, whatever the profile says
    dpi_stages: tuple[int, ...] = ()  # [dpi] stages / sniper / start / colors; empty = leave DPI to the mouse
    dpi_sniper: int | None = None
    dpi_start: int = 1
    dpi_library: str = ""  # path to iCUE's dpi.cuelibrary (default: ../dpi/dpi.cuelibrary next to the profiles folder)
    dpi_colors: tuple[str, ...] = ()  # hex, sniper first then stages; colours the DPI light


def load_overrides(path: str | Path) -> Overrides:
    import tomllib

    data = tomllib.loads(Path(path).read_text())
    o = Overrides(ignored=DEFAULT_IGNORED | {norm(c) for c in data.get("ignore", {}).get("classes", [])},
                  steam_libraries=tuple(data.get("steam", {}).get("libraries", [])),
                  skip_leds=frozenset(data.get("lighting", {}).get("skip", [])),
                  dpi_stages=tuple(data.get("dpi", {}).get("stages", ())), dpi_sniper=data.get("dpi", {}).get("sniper"),
                  dpi_start=data.get("dpi", {}).get("start", 1), dpi_library=data.get("dpi", {}).get("library", ""), dpi_colors=tuple(data.get("dpi", {}).get("colors", ())))
    for entry in data.get("profile", []):
        name = entry["name"]
        if "class" in entry:
            o.classes[name] = {norm(c) for c in ([entry["class"]] if isinstance(entry["class"], str) else entry["class"])}
        if "title" in entry:
            o.titles[name] = entry["title"]
    return o


class RuleSet:
    def __init__(self, profiles: list[Profile], steam: SteamLibrary | None = None, overrides: Overrides | None = None):
        self.overrides = overrides or Overrides()
        self.ignored = {norm(c) for c in self.overrides.ignored}
        steam = steam or SteamLibrary()
        self.rules: list[Rule] = []
        self.default = next((p for p in profiles if p.is_initial), None)
        self.unresolved_steam: dict[str, list[str]] = {}  # profile name -> install dirs with no app ID here
        for p in profiles:
            if p.is_hardware or not p.linked_programs:
                continue
            r = Rule(p)
            for path in p.linked_programs:
                r.exes.add(ntpath.basename(path.replace("/", "\\")).lower())
                d = installdir_from_path(path)
                if d:
                    r.installdirs.add(d)
                    appid = steam.appid_for_installdir(d)
                    if appid:
                        r.appids.add(appid)
            r.exes.discard("")
            if r.installdirs and not r.appids:
                self.unresolved_steam[p.name] = sorted(r.installdirs)
            r.classes = set(self.overrides.classes.get(p.name, ()))
            if p.name in self.overrides.titles:
                r.title = re.compile(self.overrides.titles[p.name])
            self.rules.append(r)

    def is_ignored(self, w: WindowInfo) -> bool:
        return bool(w.names() & self.ignored)

    def match(self, w: WindowInfo) -> Match:
        scored = sorted(((*r.score(w), r) for r in self.rules), key=lambda t: -t[0])
        if not scored or scored[0][0] == 0:
            return Match(self.default, 0, "no linked program matched; using default")
        top, why, first = scored[0]
        ties = [r.profile for s, _, r in scored[1:] if s == top]
        return Match(first.profile, top, why, ties)

    def ambiguities(self) -> dict[str, list[str]]:
        """Exe names shared by several profiles with no title/class override to tell them apart."""
        by_exe: dict[str, list[Rule]] = {}
        for r in self.rules:
            for e in r.exes:
                by_exe.setdefault(e, []).append(r)
        return {e: [r.profile.name for r in rs] for e, rs in by_exe.items()
                if len(rs) > 1 and sum(1 for r in rs if not r.title) > 1}


class Switcher:
    """Debounces focus events and reports profile changes to ``apply``."""

    def __init__(self, rules: RuleSet, apply: Callable[[Profile, Match], None]):
        self.rules = rules
        self.apply = apply
        self.current: Profile | None = None

    def on_window(self, w: WindowInfo) -> Match | None:
        if self.rules.is_ignored(w):
            return None
        m = self.rules.match(w)
        if m.score and self.current in m.ties:  # paired profiles (two profiles for one program): keep the one in use
            return m
        if m.profile is not None and m.profile is not self.current:
            self.current = m.profile
            self.apply(m.profile, m)
        return m
