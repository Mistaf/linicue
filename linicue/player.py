"""Turn button presses into key output, following iCUE's action semantics.

  * KeyRemap OnBoth: key held while the button is held; OnPress: a tap.
  * Macro OnPress: run once (a second press restarts it); WhilePressed: loop until release;
    Toggle: loop until the next press.  RepeatConstantly loops with a constant/random gap.
  * Cancelling a macro releases every key it still holds, so nothing sticks.
"""
from __future__ import annotations

import asyncio
import random
import re
import shlex
import struct
import subprocess
from typing import Callable, Protocol

from . import evcodes as ev
from . import keys
from .profile import (Action, KeyRemapAction, LaunchAction, MacroAction, MediaAction, ProfileSwitchAction,
                      TextAction)


_WINDOWS_PATH = re.compile(r'^\s*"?[A-Za-z]:[\\/]|^\s*\\\\')


def looks_windows(text: str) -> bool:
    """``C:\\Games\\x.exe`` or ``\\\\server\\share``: imported from iCUE, can never run on Linux."""
    return bool(_WINDOWS_PATH.match(text))


def _spawn(*argv: str):
    return asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, start_new_session=True)


class Sink(Protocol):
    def key(self, code: int, down: bool) -> None: ...
    def rel(self, code: int, value: int) -> None: ...


class Player:
    def __init__(self, sink: Sink, on_switch: Callable[[ProfileSwitchAction], None] = lambda a: None,
                 sleep=asyncio.sleep, log: Callable[[str], None] = lambda m: None,
                 on_dpi: Callable[[int, bool], None] = lambda fn, down: None, spawn=_spawn):
        self.sink, self.on_switch, self.sleep, self.log, self.on_dpi = sink, on_switch, sleep, log, on_dpi
        self.spawn = spawn  # starts a program; replaceable for tests
        self.tasks: dict[str, asyncio.Task] = {}  # button -> running macro
        self.held: dict[str, list[int]] = {}  # button -> codes this button holds down
        self.toggled: set[str] = set()

    # --- entry point ---------------------------------------------------------
    def button(self, name: str, action: Action | None, pressed: bool) -> None:
        if action is None:
            return
        if isinstance(action, KeyRemapAction):
            self._remap(name, action, pressed)
        elif isinstance(action, MacroAction):
            self._macro(name, action, pressed)
        elif pressed:  # one-shot actions fire on press
            self._oneshot(action)

    # --- actions -------------------------------------------------------------
    def _remap(self, name: str, a: KeyRemapAction, pressed: bool) -> None:
        names = [a.key] if a.key else list(a.keystroke)
        targets = [keys.resolve(n) for n in names]
        if a.hints.when == "OnPress":
            if pressed:
                self._tap(targets)
            return
        if pressed:
            self.held[name] = [t.code for t in targets if t.kind == "key"]
            for t in targets:
                self._press(t, True)
        else:
            for t in reversed(targets):
                self._press(t, False)
            self.held.pop(name, None)

    def _press(self, t: keys.Target, down: bool) -> None:
        if t.kind == "key":
            self.sink.key(t.code, down)
        elif t.kind == "dpi":
            self.on_dpi(t.code, down)
        elif down:  # wheel tilt is a single step on press
            self.sink.rel(t.code, t.value)

    def _tap(self, targets: list[keys.Target]) -> None:
        for t in targets:
            self._press(t, True)
        for t in reversed(targets):
            self._press(t, False)

    def _oneshot(self, a: Action) -> None:
        if isinstance(a, MediaAction):
            code = keys.resolve_media(a.media)
            self.sink.key(code, True)
            self.sink.key(code, False)
        elif isinstance(a, ProfileSwitchAction):
            self.on_switch(a)
        elif isinstance(a, TextAction):
            asyncio.ensure_future(self._type(a))
        elif isinstance(a, LaunchAction):
            self._launch_action(a)
        else:
            self.log(f"unsupported action {a.type}")

    def _launch_action(self, a: LaunchAction) -> None:
        """Run a program (command line) or open an address/file with xdg-open. Windows paths from iCUE are skipped."""
        target = a.path or a.url
        if not target:
            return
        if looks_windows(target):
            self.log(f"skipped launch action {a.name!r}: {target!r} is a Windows path")
            return
        try:
            argv = shlex.split(target) if a.path else ["xdg-open", target]
        except ValueError as e:
            self.log(f"launch action {a.name!r}: cannot read the command ({e})")
            return
        asyncio.ensure_future(self._launch(argv))

    async def _launch(self, argv: list[str]) -> None:
        try:
            proc = await self.spawn(*argv)
            await proc.wait()  # reaps the child so it never lingers as a zombie
        except OSError as e:
            self.log(f"launch failed: {argv[0]}: {e}")

    async def _type(self, a: TextAction) -> None:
        for ch in a.text:
            name = ch.upper() if ch.isalnum() else {" ": "Space"}.get(ch)
            if name is None:  # shortcut: letters, digits and space only; extend when a profile needs more
                self.log(f"text action: cannot type {ch!r}")
                continue
            t = keys.resolve(name)
            shift = ch.isupper()
            if shift:
                self.sink.key(ev.KEY_LEFTSHIFT, True)
            self._tap([t])
            if shift:
                self.sink.key(ev.KEY_LEFTSHIFT, False)
            await self.sleep(a.char_delay_ms / 1000)

    # --- macros --------------------------------------------------------------
    def _macro(self, name: str, a: MacroAction, pressed: bool) -> None:
        running = name in self.tasks and not self.tasks[name].done()
        when = a.hints.when
        if when == "WhilePressed":
            if pressed and not running:
                self._start(name, a, loop=True)
            elif not pressed:
                self._stop(name)
        elif when == "Toggle":
            if pressed:
                self._stop(name) if running else self._start(name, a, loop=True)
        elif pressed:  # OnPress / OnBoth
            if running and a.hints.restart_on_second_exec:
                self._stop(name)
                self._start(name, a, loop=a.repeat.mode == "RepeatConstantly")
            elif running and a.hints.terminate_on_second_exec:
                self._stop(name)
            elif not running:
                self._start(name, a, loop=a.repeat.mode == "RepeatConstantly")

    def _start(self, name: str, a: MacroAction, loop: bool) -> None:
        self.tasks[name] = asyncio.ensure_future(self._run(name, a, loop))

    def _stop(self, name: str) -> None:
        t = self.tasks.pop(name, None)
        if t:
            t.cancel()

    async def _run(self, name: str, a: MacroAction, loop: bool) -> None:
        down: list[int] = []
        try:
            while True:
                for e in a.events:
                    if e.kind == "delay":
                        hi = e.delay_max_ms if e.delay_max_ms is not None else e.delay_ms
                        await self.sleep(random.randint(e.delay_ms, hi) / 1000)
                    elif e.kind == "mouse":
                        code = keys.MACRO_MOUSE_BUTTONS[e.button]
                        self._macro_key(down, code, e.pressed)
                    else:
                        for k in e.keys if e.pressed else reversed(e.keys):
                            t = keys.resolve(k)
                            if t.kind == "key":
                                self._macro_key(down, t.code, e.pressed)
                            elif t.kind == "rel" and e.pressed:
                                self.sink.rel(t.code, t.value)
                if not loop:
                    return
                lo, hi = (a.repeat.random_delay if a.repeat.delay_mode == "Random" else (a.repeat.delay,) * 2)
                await self.sleep(random.randint(lo, hi) / 1000)
        finally:  # cancelled or finished: never leave a key stuck down
            for code in reversed(down):
                self.sink.key(code, False)

    def _macro_key(self, down: list[int], code: int, pressed: bool) -> None:
        self.sink.key(code, pressed)
        if pressed:
            down.append(code)
        elif code in down:
            down.remove(code)

    def release_all(self) -> None:
        """Call on profile change or shutdown."""
        for name in list(self.tasks):
            self._stop(name)
        for codes in self.held.values():
            for c in reversed(codes):
                self.sink.key(c, False)
        self.held.clear()


class UInputSink:
    """Virtual keyboard+mouse via /dev/uinput (stdlib only; needs write access to the node)."""

    _EVENT = struct.Struct("llHHi")

    def __init__(self, name: str = "linicue virtual input"):
        import fcntl
        import os

        self._os = os
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        w = lambda req, arg: fcntl.ioctl(self.fd, req, arg)
        w(0x40045564, ev.EV_KEY)  # UI_SET_EVBIT
        w(0x40045564, ev.EV_REL)
        w(0x40045564, ev.EV_SYN)
        for code in range(1, 0x2ff):  # shortcut: enable every key/button; trim if a desktop dislikes it
            w(0x40045565, code)  # UI_SET_KEYBIT
        for code in (ev.REL_X, ev.REL_Y, ev.REL_WHEEL, ev.REL_HWHEEL):
            w(0x40045566, code)  # UI_SET_RELBIT
        # struct uinput_setup: input_id{bustype,vendor,product,version}, name[80], ff_effects_max
        w(0x405C5503, struct.pack("4H80sI", 0x06, 0x1209, 0x0001, 1, name.encode(), 0))  # UI_DEV_SETUP
        w(0x5501, 0)  # UI_DEV_CREATE

    def _emit(self, type_: int, code: int, value: int) -> None:
        self._os.write(self.fd, self._EVENT.pack(0, 0, type_, code, value))
        self._os.write(self.fd, self._EVENT.pack(0, 0, ev.EV_SYN, ev.SYN_REPORT, 0))

    def key(self, code: int, down: bool) -> None:
        self._emit(ev.EV_KEY, code, int(down))

    def rel(self, code: int, value: int) -> None:
        self._emit(ev.EV_REL, code, value)

    def close(self) -> None:
        import fcntl

        fcntl.ioctl(self.fd, 0x5502, 0)  # UI_DEV_DESTROY
        self._os.close(self.fd)
