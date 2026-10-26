# linicue

Linux replacement for Corsair iCUE on a **Scimitar RGB Elite** (1b1c:1b8b): imports your iCUE profiles, switches them by
focused window (KDE Plasma 6), plays their lighting, remaps the G buttons and runs their macros.

## Install (Fedora KDE)
```bash
python3 -m venv .venv && .venv/bin/pip install dbus-next pyside6
.venv/bin/python -m linicue install --dry-run     # shows what it will do
.venv/bin/python -m linicue install               # service (starts at login), "linicue" menu entry, KWin window script
```
`install` prints one command that needs root (the udev rule that lets your user open the mouse); run it once and replug the mouse.
Close any `linicue run` still open in a terminal first. `python -m linicue uninstall` reverses it (your profiles are kept).
The daemon waits for the mouse, reconnects after unplugging, and re-initialises it after suspend.

<details><summary>Doing the steps by hand instead</summary>

```bash
sudo cp udev/70-linicue.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger
kpackagetool6 --type=KWin/Script --install kwin/linicue-windowwatcher
kwriteconfig6 --file kwinrc --group Plugins --key linicue-windowwatcherEnabled true
busctl --user call org.kde.KWin /KWin org.kde.KWin reconfigure
busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting isScriptLoaded s linicue-windowwatcher   # expect: b true
```
</details>

## Your profiles
linicue keeps its own copy of your profiles in `~/.config/linicue` (your iCUE files are never changed). Import once:
```bash
.venv/bin/python -m linicue import icue-appdata/profiles     # your iCUE profiles folder; ../dpi/dpi.cuelibrary is imported too
.venv/bin/python -m linicue gui                               # edit lighting, buttons, macros, DPI and app links
```
The window saves as you edit; the running daemon reloads within a second. "Show on mouse" pins the selected profile on the
mouse so you can watch lighting changes live (it needs the daemon running). Optional settings: `cp rules.example.toml ~/.config/linicue/rules.toml`.

## Run
```bash
.venv/bin/python -m linicue run --dry-run                # reads the mouse, logs what it would do; writes nothing
.venv/bin/python -m linicue run                          # the real thing; Ctrl-C hands the mouse back to its firmware
.venv/bin/python -m linicue run --profile Discord        # pin one profile, no window tracking
.venv/bin/python -m linicue run icue-appdata/profiles    # read iCUE's own files directly instead (read-only)
```
If you used `install`, the daemon is already running as a service: `systemctl --user status linicue`, `journalctl --user -u linicue -f`.

## Other commands
`install`, `uninstall`, `import`, `gui`, `list`, `show`, `rules` (check app matching), `preview` (lighting only), `lights` (LED test, `--restore` undoes it),
`tools/probe.py` (read-only device probe).

## Status
Verified on hardware: lighting, DPI stages and sniper, button actions, profile switching by window. The configuration window and
the store were tested headlessly (see `tests/`), not yet on a real desktop. Not implemented: polling rate, onboard (hardware)
profiles, effects other than static colour, gradient and temperature, launch-app actions (Windows paths), macro mouse-button recording.
