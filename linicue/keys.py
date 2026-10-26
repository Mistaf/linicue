"""Map iCUE key names (HID usage style) to Linux evdev events.

Names come from iCUE's UniversalKey enum.  Keys are physical positions on both
sides (HID usages vs. evdev scancodes), so the mapping is layout independent.
"""
from __future__ import annotations

import string
from dataclasses import dataclass

from . import evcodes as ev


DPI_UP, DPI_DOWN, SNIPER = 1, 2, 3


@dataclass(frozen=True)
class Target:
    """What to emit: a key/button press, a relative axis step, or a DPI function (code = DPI_UP/DPI_DOWN/SNIPER)."""
    kind: str  # "key" | "rel" | "dpi"
    code: int
    value: int = 0  # rel only

    @property
    def is_button(self) -> bool:
        return self.kind == "key" and self.code >= ev.BTN_MISC


class UnknownKey(KeyError):
    pass


def _build() -> dict[str, Target]:
    t: dict[str, Target] = {}

    def key(name: str, linux: str) -> None:
        t[name] = Target("key", getattr(ev, linux))

    for c in string.ascii_uppercase:
        key(c, f"KEY_{c}")
    for c in "1234567890":
        key(c, f"KEY_{c}")
    for n in range(1, 25):
        key(f"F{n}", f"KEY_F{n}")

    for name, linux in {
        "Enter": "KEY_ENTER", "Escape": "KEY_ESC", "Backspace": "KEY_BACKSPACE", "Tab": "KEY_TAB",
        "Space": "KEY_SPACE", "MinusAndUnderscore": "KEY_MINUS", "EqualsAndPlus": "KEY_EQUAL",
        "BracketLeft": "KEY_LEFTBRACE", "BracketRight": "KEY_RIGHTBRACE", "Backslash": "KEY_BACKSLASH",
        "NonUsTilde": "KEY_BACKSLASH", "NonUsBackslash": "KEY_102ND",
        "SemicolonAndColon": "KEY_SEMICOLON", "ApostropheAndDoubleQuote": "KEY_APOSTROPHE",
        "GraveAccentAndTilde": "KEY_GRAVE", "CommaAndLessThan": "KEY_COMMA",
        "PeriodAndBiggerThan": "KEY_DOT", "SlashAndQuestionMark": "KEY_SLASH", "CapsLock": "KEY_CAPSLOCK",
        "PrintScreen": "KEY_SYSRQ", "ScrollLock": "KEY_SCROLLLOCK", "PauseBreak": "KEY_PAUSE",
        "Insert": "KEY_INSERT", "Home": "KEY_HOME", "PageUp": "KEY_PAGEUP", "Delete": "KEY_DELETE",
        "End": "KEY_END", "PageDown": "KEY_PAGEDOWN", "UpArrow": "KEY_UP", "DownArrow": "KEY_DOWN",
        "LeftArrow": "KEY_LEFT", "RightArrow": "KEY_RIGHT", "Menu": "KEY_COMPOSE", "Help": "KEY_HELP",
        "NumLock": "KEY_NUMLOCK",
        "LeftCtrl": "KEY_LEFTCTRL", "LeftShift": "KEY_LEFTSHIFT", "LeftAlt": "KEY_LEFTALT",
        "LeftGui": "KEY_LEFTMETA", "RightCtrl": "KEY_RIGHTCTRL", "RightShift": "KEY_RIGHTSHIFT",
        "RightAlt": "KEY_RIGHTALT", "RightGui": "KEY_RIGHTMETA",
        "KeypadSlash": "KEY_KPSLASH", "KeypadAsterisk": "KEY_KPASTERISK", "KeypadMinus": "KEY_KPMINUS",
        "KeypadPlus": "KEY_KPPLUS", "KeypadEnter": "KEY_KPENTER", "KeypadEquals": "KEY_KPEQUAL",
        "KeypadComma": "KEY_KPCOMMA", "KeypadPeriodAndDelete": "KEY_KPDOT",
        "VolumeUp": "KEY_VOLUMEUP", "VolumeDown": "KEY_VOLUMEDOWN", "Mute": "KEY_MUTE",
        "PlayPause": "KEY_PLAYPAUSE", "ScanNextTrack": "KEY_NEXTSONG", "ScanPreviousTrack": "KEY_PREVIOUSSONG",
        "Stop": "KEY_STOPCD",
        # Mouse buttons by HID button index (1..8); see MOUSE_BUTTON_NOTE.
        "Mouse1": "BTN_LEFT", "Mouse2": "BTN_RIGHT", "Mouse3": "BTN_MIDDLE", "Mouse4": "BTN_SIDE",
        "Mouse5": "BTN_EXTRA",
    }.items():
        key(name, linux)
    for n in range(10):
        key(f"Keypad{n}", f"KEY_KP{n}")

    # iCUE's button list reads: Left, Right, Middle, Back, Forward, DPI Up, DPI Down, Sniper - so these are functions.
    t["Mouse6"], t["Mouse7"], t["Mouse8"] = Target("dpi", DPI_UP), Target("dpi", DPI_DOWN), Target("dpi", SNIPER)

    # Wheel tilt is a horizontal scroll step, not a button.
    for name, v in (("Mouse_TiltLeft", -1), ("Mouse_TiltRight", 1),
                    ("MouseWheelTiltLeft", -1), ("MouseWheelTiltRight", 1)):
        t[name] = Target("rel", ev.REL_HWHEEL, v)
    return t


KEYS: dict[str, Target] = _build()

# iCUE macro MouseButton events use 1-based HID button numbers.
MACRO_MOUSE_BUTTONS = {1: ev.BTN_LEFT, 2: ev.BTN_RIGHT, 3: ev.BTN_MIDDLE, 4: ev.BTN_SIDE, 5: ev.BTN_EXTRA}

MEDIA = {
    "PlayPause": ev.KEY_PLAYPAUSE, "NextTrack": ev.KEY_NEXTSONG, "PrevTrack": ev.KEY_PREVIOUSSONG,
    "Stop": ev.KEY_STOPCD, "Mute": ev.KEY_MUTE, "VolumeUp": ev.KEY_VOLUMEUP, "VolumeDown": ev.KEY_VOLUMEDOWN,
}



def resolve(name: str) -> Target:
    try:
        return KEYS[str(name)]
    except KeyError:
        raise UnknownKey(name) from None


def resolve_media(name: str) -> int:
    try:
        return MEDIA[name]
    except KeyError:
        raise UnknownKey(name) from None
