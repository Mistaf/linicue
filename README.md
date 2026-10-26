# linicue

Linux replacement for Corsair iCUE on a **Scimitar RGB Elite** (1b1c:1b8b): imports your iCUE profiles, switches them by
focused window (KDE Plasma 6), plays their lighting, remaps the G buttons, runs their macros and sets the DPI.

## Install (Fedora KDE)
```bash
python3 -m venv ~/.local/share/linicue/venv
~/.local/share/linicue/venv/bin/pip install ".[gui]"          # run inside the project folder (or pass the wheel's path)
mkdir -p ~/.local/bin && ln -sf ~/.local/share/linicue/venv/bin/linicue ~/.local/bin/linicue   # then open a new terminal
linicue install --dry-run     # shows what it will do
linicue install               # service (starts at login), "linicue" menu entry, KWin window script, example config
```
`install` prints one command that needs root (the udev rule that lets your user open the mouse); run it once and replug the mouse.
Close any `linicue run` still open in a terminal first. `linicue uninstall` reverses it (your profiles are kept).
Everything lives under your home folder, so the project folder can be anywhere, or deleted, once it is installed.
The daemon waits for the mouse, reconnects after unplugging, and re-initialises it after suspend.

**Updating:** run the same `pip install ".[gui]"` again from the new source, then `systemctl --user restart linicue`
(`linicue install` also works and refreshes the KWin script; log out and in afterwards so KWin loads it). `linicue --version` and the first lines of
`journalctl --user -u linicue -b` show which version is running.

**From the source folder, without installing:** `python3 -m linicue ...` works there too (needs `dbus-next`, and `PySide6` for the window).

<details><summary>Doing the steps by hand instead</summary>

```bash
D=$(python3 -c 'import linicue.install as i; print(i.DATA)')
sudo cp $D/udev/70-linicue.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger
kpackagetool6 --type=KWin/Script --install $D/kwin/linicue-windowwatcher
kwriteconfig6 --file kwinrc --group Plugins --key linicue-windowwatcherEnabled true
busctl --user call org.kde.KWin /KWin org.kde.KWin reconfigure
busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting isScriptLoaded s linicue-windowwatcher   # expect: b true
```
</details>

## Your profiles
linicue keeps its own copy of your profiles in `~/.config/linicue` (your iCUE files are never changed). Import once:
```bash
linicue import <iCUE profiles folder>     # ../dpi/dpi.cuelibrary next to it is imported too
linicue gui                               # edit lighting, buttons, macros, DPI, mouse settings and app links
```
Or open **linicue** from the application menu. The window saves as you edit; the running daemon reloads within a second.
"Show on mouse" pins the selected profile on the mouse so you can watch lighting changes live (it needs the daemon running).
Optional settings live in `~/.config/linicue/rules.toml` (`install` creates it from a commented example).

## Run
```bash
linicue run --dry-run                # reads the mouse, logs what it would do; writes nothing
linicue run                          # the real thing; Ctrl-C hands the mouse back to its firmware
linicue run --profile Discord        # pin one profile, no window tracking
linicue run <iCUE profiles folder>   # read iCUE's own files directly instead (read-only)
```
If you used `install`, the daemon already runs as a service: `systemctl --user status linicue`, `journalctl --user -u linicue -f`.

## Other commands
`install`, `uninstall`, `import`, `gui`, `status` (asks the running daemon what it is doing), `version`, `list`, `show`, `rules` (check app matching), `preview` (lighting only),
`lights` (LED test, `--restore` undoes it), `probe` (read-only device probe; run as `sudo $(which linicue) probe`), `pollrate` (measures the real polling rate).

## Status
Verified on hardware: lighting, DPI stages and sniper, button actions, profile switching by window, media and function keys,
polling rate. Tested without hardware (see `tests/`): the configuration window, the store, reconnect and resume handling, the
installer, angle snapping, the extra lighting effects (rainbow, rainbow wave, pulse, blink, visor), launch-program / open-address
actions, and mouse clicks in macros. Not implemented: writing the mouse's onboard (hardware) profiles (iCUE cannot read them back
from this mouse either, so it was left alone), lift height, water-colour, spiral and screen effects, recording mouse clicks
(add them by hand), typing anything but letters, digits and spaces with the "type text" action.
The extra lighting effects are approximations of iCUE's (loop length only; iCUE's "speed" values are not interpreted).

## Development
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[gui]"
.venv/bin/python -m unittest discover -s tests -t .
```
The window tests run headless (they need PySide6). Tests that read your own iCUE files (`profiles-src/`, `icue-appdata/`) are skipped when
those folders are absent; both are git-ignored, as is the probe capture. Never commit them: they hold your profiles, paths and settings.

## Disclaimer and credits
linicue is an independent project, not affiliated with or endorsed by Corsair; "Corsair" and "iCUE" are trademarks of their owners.
It sends the mouse the same USB commands iCUE does. The byte layouts were read from iCUE's own program code on a Windows install for
interoperability (no iCUE code or files are included here) and cross-checked against the open-source projects
[ckb-next](https://github.com/ckb-next/ckb-next) and [OpenRGB](https://openrgb.org), which documented this protocol family first.
Use it at your own risk: while it runs it changes how the mouse behaves (nearly everything it writes is temporary, but the polling rate
may be stored in the mouse), and it deliberately never writes the mouse's onboard profile storage.
