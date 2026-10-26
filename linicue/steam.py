"""Find Steam app IDs from the install directories named in iCUE's linked paths."""
from __future__ import annotations

import re
from pathlib import Path

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')
_INSTALLDIR_RE = re.compile(r"steamapps[/\\]common[/\\]([^/\\]+)", re.IGNORECASE)

DEFAULT_ROOTS = (
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
)


def parse_vdf(text: str) -> dict:
    """Parse Valve's KeyValues text format (libraryfolders.vdf, appmanifest_*.acf)."""
    stack: list[dict] = [{}]
    key: str | None = None
    for m in _TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            child: dict = {}
            stack[-1][key] = child  # type: ignore[index]
            stack.append(child)
            key = None
        elif brace == "}":
            stack.pop()
        elif key is None:
            key = s.replace("\\\\", "\\")
        else:
            stack[-1][key] = s.replace("\\\\", "\\")
            key = None
    return stack[0]


def installdir_from_path(path: str) -> str | None:
    """``D:/Games/steamapps/common/Foo/bin/Foo.exe`` -> ``Foo``."""
    m = _INSTALLDIR_RE.search(path)
    return m.group(1) if m else None


class SteamLibrary:
    def __init__(self, installdirs: dict[str, int] | None = None):
        self._by_dir = {k.lower(): v for k, v in (installdirs or {}).items()}

    def appid_for_installdir(self, name: str) -> int | None:
        return self._by_dir.get(name.lower())

    @classmethod
    def discover(cls, roots: tuple[str, ...] = DEFAULT_ROOTS, extra_libraries: tuple[str, ...] = ()) -> "SteamLibrary":
        libs: list[Path] = [Path(p) for p in extra_libraries]
        for root in roots:
            base = Path(root).expanduser()
            vdf = base / "steamapps" / "libraryfolders.vdf"
            if not vdf.is_file():
                continue
            libs.append(base)
            folders = parse_vdf(vdf.read_text(errors="replace")).get("libraryfolders", {})
            for entry in folders.values():
                if isinstance(entry, dict) and "path" in entry:
                    libs.append(Path(entry["path"]))
        found: dict[str, int] = {}
        for lib in dict.fromkeys(libs):
            for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
                state = parse_vdf(acf.read_text(errors="replace")).get("AppState", {})
                if "installdir" in state and str(state.get("appid", "")).isdigit():
                    found[state["installdir"]] = int(state["appid"])
        return cls(found)
