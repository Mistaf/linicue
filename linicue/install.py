"""`python -m linicue install` / `uninstall`: the per-user setup (service, menu entry, KWin script)."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent  # what to put on PYTHONPATH: the source folder, or site-packages when installed
DATA = Path(__file__).resolve().parent / "data"  # KWin script, udev rule and example config travel with the package
KWIN_ID = "linicue-windowwatcher"
UDEV_RULE = Path("/etc/udev/rules.d/70-linicue.rules")


def unit_text(python: str, root: Path) -> str:
    return f"""[Unit]
Description=linicue (Corsair Scimitar RGB Elite profiles, macros and lighting)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Environment=PYTHONPATH={root}
ExecStart={python} -m linicue run
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""


def desktop_text(python: str, root: Path) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=linicue
Comment=Scimitar RGB Elite: profiles, lighting, buttons, macros and DPI
Exec=env PYTHONPATH={root} {python} -m linicue gui
Icon=input-mouse
Terminal=false
Categories=Settings;HardwareSettings;
"""


class Installer:
    def __init__(self, home: Path = Path.home(), python: str = sys.executable, root: Path = ROOT, dry_run: bool = False,
                 runner: Callable[[list[str]], tuple[int, str]] | None = None, say: Callable[[str], None] = print,
                 which: Callable[[str], str | None] = shutil.which, data: Path = DATA):
        self.home, self.python, self.root, self.dry, self.say, self.which = home, python, root, dry_run, say, which
        self.data = data
        self.runner = runner or self._run
        self.unit = home / ".config/systemd/user/linicue.service"
        self.desktop = home / ".local/share/applications/linicue.desktop"

    @staticmethod
    def _run(cmd: list[str]) -> tuple[int, str]:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def write(self, path: Path, text: str) -> None:
        self.say(f"write {path}")
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def cmd(self, *cmd: str) -> tuple[int, str]:
        self.say("run   " + " ".join(cmd))
        return (0, "") if self.dry else self.runner(list(cmd))

    # --- install ----------------------------------------------------------------------------
    def install(self) -> None:
        for mod, pip in (("dbus_next", "dbus-next"), ("PySide6", "pyside6")):
            if importlib.util.find_spec(mod) is None:
                self.say(f"note: {pip} is not installed for {self.python}; run: {self.python} -m pip install {pip}")
        self.write(self.unit, unit_text(self.python, self.root))
        self.write(self.desktop, desktop_text(self.python, self.root))
        rules = self.home / ".config/linicue/rules.toml"  # the example is all comments, so it changes nothing until edited
        if rules.exists():
            self.say(f"keep  {rules} (already there)")
        else:
            self.write(rules, (self.data / "rules.example.toml").read_text())
        self._kwin_install()
        if self.which("systemctl"):
            self.say("note: close any `linicue run` still open in a terminal first, or two copies will fight over the mouse")
            self.cmd("systemctl", "--user", "daemon-reload")
            self.cmd("systemctl", "--user", "enable", "linicue.service")
            self.cmd("systemctl", "--user", "restart", "linicue.service")  # also picks up a changed service file or new code
        else:
            self.say("systemctl not found: start it yourself with `python -m linicue run`")
        if not UDEV_RULE.exists():
            self.say(f"\nOne step needs root. Run this once, then replug the mouse:\n  sudo cp {self.data}/udev/70-linicue.rules /etc/udev/rules.d/ "
                     "&& sudo udevadm control --reload && sudo udevadm trigger")
        self.say("\nDone. Open “linicue” from the application menu, or run: " f"{self.python} -m linicue gui")

    def _kwin_install(self) -> None:
        if not self.which("kpackagetool6"):
            self.say("kpackagetool6 not found: install the KWin script by hand (see README)")
            return
        src = str(self.data / "kwin" / KWIN_ID)
        _, listing = self.cmd("kpackagetool6", "--type=KWin/Script", "--list")
        self.cmd("kpackagetool6", "--type=KWin/Script", "--upgrade" if KWIN_ID in listing else "--install", src)
        self.cmd("kwriteconfig6", "--file", "kwinrc", "--group", "Plugins", "--key", f"{KWIN_ID}Enabled", "true")
        self.cmd("busctl", "--user", "call", "org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure")

    # --- uninstall ----------------------------------------------------------------------------
    def uninstall(self) -> None:
        if self.which("systemctl"):
            self.cmd("systemctl", "--user", "disable", "--now", "linicue.service")
        for path in (self.unit, self.desktop):
            self.say(f"remove {path}")
            if not self.dry:
                path.unlink(missing_ok=True)
        if self.which("systemctl"):
            self.cmd("systemctl", "--user", "daemon-reload")
        if self.which("kpackagetool6"):
            self.cmd("kwriteconfig6", "--file", "kwinrc", "--group", "Plugins", "--key", f"{KWIN_ID}Enabled", "false")
            self.cmd("kpackagetool6", "--type=KWin/Script", "--remove", KWIN_ID)
        self.say("Removed. Your profiles in ~/.config/linicue are untouched; the udev rule (if installed) is left in place.")


def main(args: list[str], uninstall: bool = False) -> int:
    inst = Installer(dry_run="--dry-run" in args)
    (inst.uninstall if uninstall else inst.install)()
    return 0
