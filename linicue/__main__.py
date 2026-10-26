"""``python -m linicue list|show <profile-dir> [name]`` — inspect imported iCUE profiles."""
from __future__ import annotations

import argparse
import ntpath
import sys

from .profile import MacroAction, load_profiles


def _exe(path: str) -> str:
    return ntpath.basename(path.replace("/", "\\"))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["--version"], ["version"]):
        from . import __version__
        print(f"linicue {__version__}")
        return 0
    if argv[:1] == ["status"]:
        from .dbus_service import status_main
        return status_main()
    if argv[:1] == ["probe"]:
        from .probe import main as probe_main
        return probe_main(argv[1:])
    if argv[:1] == ["pollrate"]:
        from .pollrate import main as pollrate_main
        return pollrate_main(argv[1:])
    if argv[:1] in (["install"], ["uninstall"]):
        from .install import main as install_main
        return install_main(argv[1:], uninstall=argv[0] == "uninstall")
    if argv[:1] == ["gui"]:
        from .gui.window import main as gui_main
        return gui_main()
    if argv[:1] == ["import"]:
        from . import store
        n = store.import_icue(argv[1])
        print(f"imported {n} profiles into {store.CONFIG_DIR}")
        return 0
    if argv[:1] == ["run"]:
        import asyncio
        from .daemon import run
        return asyncio.run(run(argv[1:]))
    if argv[:1] == ["preview"]:
        from .lighting import preview_cli
        return preview_cli(argv[1:])
    if argv[:1] == ["lights"]:  # flags are its own, so skip argparse here
        from .nxp import lights_cli
        return lights_cli(argv[1:])
    ap = argparse.ArgumentParser(prog="linicue")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="one line per profile")
    ls.add_argument("dir")
    sh = sub.add_parser("show", help="bindings and lighting of one profile")
    sh.add_argument("dir")
    sh.add_argument("name")
    rl = sub.add_parser("rules", help="check app-matching rules (run on the machine that has Steam)")
    rl.add_argument("dir")
    rl.add_argument("--config", help="rules.toml with overrides")
    sub.add_parser("lights", help="LED test: python -m linicue lights [--send] [--identify|--slot N] [--color RRGGBB] [--restore]")
    args = ap.parse_args(argv)

    profiles = load_profiles(args.dir)
    if args.cmd == "list":
        for p in profiles:
            exes = sorted({_exe(x) for x in p.linked_programs})
            kind = "hw" if p.is_hardware else "sw"
            print(f"{kind}  {p.name:<30} {len(p.mouse.bindings):>3} bindings  {', '.join(exes)}")
        return 0

    if args.cmd == "rules":
        from .steam import SteamLibrary
        from .switcher import Overrides, RuleSet, load_overrides

        o = load_overrides(args.config) if args.config else Overrides()
        rs = RuleSet(profiles, SteamLibrary.discover(extra_libraries=o.steam_libraries), o)
        print(f"{len(rs.rules)} program rules; default profile: {rs.default.name if rs.default else 'none'}")
        for exe, names in sorted(rs.ambiguities().items()):
            print(f"paired profiles sharing {exe}: {', '.join(names)}  (switch with the profile-switch button)")
        for name, dirs in sorted(rs.unresolved_steam.items()):
            print(f"no Steam app ID found for {name}: {', '.join(dirs)}  (matches by Wine exe name instead)")
        return 0

    matches = [p for p in profiles if p.name.lower() == args.name.lower()]
    if not matches:
        print(f"no profile named {args.name!r}", file=sys.stderr)
        return 1
    for p in matches:
        print(f"{p.name}  {p.id}")
        print("  programs:", ", ".join(sorted({_exe(x) for x in p.linked_programs})) or "-")
        for b in p.mouse.bindings:
            if not b.button:
                continue
            a = b.action
            extra = f"{len(a.events)} events" if isinstance(a, MacroAction) else ""
            print(f"  {b.button:<20} {type(a).__name__:<22} {a.name if a else '-'} {extra}")
        for lay in p.mouse.lighting:
            e = lay.effect
            print(f"  light {lay.name}: {e.kind if e else '-'} on {', '.join(lay.leds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
