"""Buttons tab: what each G button does, with key capture, a macro editor (with recording) and the action dialog."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import keys
from ..keys import DPI_DOWN, DPI_UP, SNIPER
from ..profile import (Action, Binding, ExecHints, KeyRemapAction, LaunchAction, MacroAction, MacroEvent, MediaAction,
                       ProfileSwitchAction, RepeatOptions, TextAction)

BUTTONS = [(f"MouseG{i}", f"G{i}") for i in range(1, 13)] + [("MouseDpiToggle", "DPI button (top)"), ("MouseProfileSwitch", "Profile switch button (top)")]
MEDIA = {"PlayPause": "Play / Pause", "NextTrack": "Next track", "PrevTrack": "Previous track", "Stop": "Stop",
         "Mute": "Mute", "VolumeUp": "Volume up", "VolumeDown": "Volume down"}
DPI_FUNCTIONS = {"Mouse8": "Sniper (lower DPI while held)", "Mouse6": "DPI up", "Mouse7": "DPI down"}
PRETTY = {"LeftCtrl": "Ctrl", "RightCtrl": "Right Ctrl", "LeftShift": "Shift", "RightShift": "Right Shift", "LeftAlt": "Alt",
          "RightAlt": "Alt Gr", "LeftGui": "Meta", "RightGui": "Right Meta", "SlashAndQuestionMark": "/", "Space": "Space",
          "MinusAndUnderscore": "-", "EqualsAndPlus": "=", "CommaAndLessThan": ",", "PeriodAndBiggerThan": ".",
          "GraveAccentAndTilde": "`", "SemicolonAndColon": ";", "ApostropheAndDoubleQuote": "'", "BracketLeft": "[",
          "BracketRight": "]", "Backslash": "\\", "UpArrow": "Up", "DownArrow": "Down", "LeftArrow": "Left", "RightArrow": "Right",
          "PlayPause": "Play / Pause", "ScanNextTrack": "Next track", "ScanPreviousTrack": "Previous track",
          "VolumeUp": "Volume up", "VolumeDown": "Volume down"}
# evdev code -> iCUE key name for keyboard keys (first name wins, so "Backslash" beats "NonUsTilde")
_BY_CODE: dict[int, str] = {}
for _name, _t in keys.KEYS.items():
    if _t.kind == "key" and _t.code < 0x100:
        _BY_CODE.setdefault(_t.code, _name)


KEY_GROUPS = {
    "Function keys (F1 – F24)": [f"F{i}" for i in range(1, 25)],
    "Navigation": ["UpArrow", "DownArrow", "LeftArrow", "RightArrow", "Home", "End", "PageUp", "PageDown", "Insert", "Delete"],
    "Editing and system": ["Enter", "Escape", "Tab", "Space", "Backspace", "CapsLock", "PrintScreen", "ScrollLock", "PauseBreak", "Menu", "Help"],
    "Keypad": [f"Keypad{i}" for i in range(10)] + ["KeypadEnter", "KeypadPlus", "KeypadMinus", "KeypadAsterisk", "KeypadSlash",
                                                    "KeypadPeriodAndDelete", "KeypadEquals", "KeypadComma", "NumLock"],
    "Punctuation": ["MinusAndUnderscore", "EqualsAndPlus", "BracketLeft", "BracketRight", "Backslash", "SemicolonAndColon",
                    "ApostropheAndDoubleQuote", "GraveAccentAndTilde", "CommaAndLessThan", "PeriodAndBiggerThan",
                    "SlashAndQuestionMark", "NonUsBackslash"],
    "Letters": [chr(c) for c in range(ord("A"), ord("Z") + 1)],
    "Numbers": list("1234567890"),
    "Modifiers": ["LeftCtrl", "RightCtrl", "LeftShift", "RightShift", "LeftAlt", "RightAlt", "LeftGui", "RightGui"],
    "Media": ["PlayPause", "ScanNextTrack", "ScanPreviousTrack", "Stop", "Mute", "VolumeUp", "VolumeDown"],
}
MEDIA_KEYS = set(KEY_GROUPS["Media"])
MEDIA_AS_KEY = {"PlayPause": "PlayPause", "NextTrack": "ScanNextTrack", "PrevTrack": "ScanPreviousTrack", "Stop": "Stop",
                "Mute": "Mute", "VolumeUp": "VolumeUp", "VolumeDown": "VolumeDown"}  # iCUE media action -> key name
MODIFIERS = [("Ctrl", "LeftCtrl"), ("Shift", "LeftShift"), ("Alt", "LeftAlt"), ("Meta", "LeftGui")]


def pretty(name: str) -> str:
    return PRETTY.get(name, name)


def describe(a: Action | None, profiles: list | None = None) -> str:
    if a is None:
        return "—"
    if isinstance(a, KeyRemapAction):
        if a.key in DPI_FUNCTIONS:
            return DPI_FUNCTIONS[a.key]
        names = [a.key] if a.key else list(a.keystroke)
        return "Key: " + " + ".join(pretty(n) for n in names) if names else "Key: (none)"
    if isinstance(a, MediaAction):
        return "Media: " + MEDIA.get(a.media, a.media)
    if isinstance(a, MacroAction):
        return f"Macro “{a.name}” ({len(a.events)} events)"
    if isinstance(a, TextAction):
        return f"Type “{a.text[:30]}”"
    if isinstance(a, ProfileSwitchAction):
        target = next((p.name for p in profiles or [] if p.id == a.target), None)
        return f"Switch to profile {target!r}" if target else "Switch profile"
    if isinstance(a, LaunchAction):
        return "Launch application (not supported on Linux)"
    return a.type or "(unknown)"


def common(name: str, when: str = "OnPress", **hints) -> dict:
    return dict(type="", name=name, id="", repeat=RepeatOptions(), hints=ExecHints(when, **hints), raw={})


def make_action(cls, type_name: str, name: str, when: str = "OnPress", **kw) -> Action:
    c = common(name, when)
    c["type"] = type_name
    return cls(**c, **kw)


class KeyStream(QPushButton):
    """Turns physical key presses into iCUE key names (via the keyboard scancode, so layout-independent)."""
    keyDown, keyUp = Signal(str), Signal(str)

    def __init__(self, text: str):
        super().__init__(text)
        self.setFocusPolicy(Qt.StrongFocus)
        self.active = False

    def focusNextPrevChild(self, forward: bool) -> bool:
        return False if self.active else super().focusNextPrevChild(forward)

    @staticmethod
    def name_for(scancode: int) -> str | None:
        return _BY_CODE.get(scancode - 8)  # Qt reports xkb keycodes = evdev + 8

    def keyPressEvent(self, e) -> None:
        name = self.name_for(e.nativeScanCode())
        if self.active and name and not e.isAutoRepeat():
            self.keyDown.emit(name)
        elif not self.active:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:
        name = self.name_for(e.nativeScanCode())
        if self.active and name and not e.isAutoRepeat():
            self.keyUp.emit(name)
        elif not self.active:
            super().keyReleaseEvent(e)


class KeyCapture(KeyStream):
    """Click, then press a key or combination; ends when all keys are released."""
    captured = Signal(list)
    PROMPT = "Click here, then press the key or combination"

    def __init__(self):
        super().__init__(self.PROMPT)
        self.combo: list[str] = []
        self.held: set[str] = set()
        self.clicked.connect(self._start)
        self.keyDown.connect(self.press)
        self.keyUp.connect(self.release)

    def set_combo(self, names: list[str]) -> None:
        self.combo = list(names)
        self.active = False
        self.setText(" + ".join(pretty(n) for n in names) if names else self.PROMPT)

    def _start(self) -> None:
        self.active, self.held = True, set()
        self.combo = []
        self.setText("Press keys now…")
        self.setFocus()

    def focusOutEvent(self, e) -> None:
        if self.active:
            self.set_combo(self.combo)
        super().focusOutEvent(e)

    def press(self, name: str) -> None:
        if not self.active:
            return
        self.held.add(name)
        if name not in self.combo:
            self.combo.append(name)
        self.setText(" + ".join(pretty(n) for n in self.combo))

    def release(self, name: str) -> None:
        self.held.discard(name)
        if self.active and not self.held and self.combo:
            self.active = False
            self.captured.emit(list(self.combo))


class KeyPicker(QGroupBox):
    """Build a combination from a list (also for keys a keyboard doesn't have, like F13-F24); all its keys are pressed together."""
    added, removedLast, cleared = Signal(list), Signal(), Signal()

    def __init__(self):
        super().__init__("Or build it from the list (also media keys, and keys your keyboard doesn't have, like F13 – F24)")
        self.mods = {name: QCheckBox(label) for label, name in MODIFIERS}
        self.group = QComboBox()
        self.group.addItems(list(KEY_GROUPS))
        self.key = QComboBox()
        self.group.currentIndexChanged.connect(self._fill_keys)
        add, last, clear = QPushButton("Add key"), QPushButton("Remove last"), QPushButton("Clear")
        add.clicked.connect(self._add)
        last.clicked.connect(self.removedLast)
        clear.clicked.connect(self.cleared)
        mods = QHBoxLayout()
        mods.addWidget(QLabel("With:"))
        for cb in self.mods.values():
            mods.addWidget(cb)
        mods.addStretch(1)
        row = QHBoxLayout()
        for w in (self.group, self.key, add, last, clear):
            row.addWidget(w)
        note = QLabel("Every key you add is pressed together and released together, e.g. F13 + F14.")
        lay = QVBoxLayout(self)
        lay.addLayout(mods)
        lay.addLayout(row)
        lay.addWidget(note)
        self._fill_keys()

    def _fill_keys(self) -> None:
        self.key.clear()
        for name in KEY_GROUPS[self.group.currentText()]:
            self.key.addItem(pretty(name) if name in PRETTY else name, name)

    def combo(self) -> list[str]:
        key = self.key.currentData()
        return [m for m, cb in self.mods.items() if cb.isChecked() and m != key] + [key]

    def _add(self) -> None:
        self.added.emit(self.combo())
        for cb in self.mods.values():  # modifiers are one-shot, so they don't stick to the next key
            cb.setChecked(False)


class MacroEditor(QWidget):
    """Event table + recorder + repeat behaviour for a MacroAction."""

    def __init__(self, macro: MacroAction):
        super().__init__()
        self.macro = macro
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Event", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        self.rec = KeyStream("● Record")
        self.rec.setCheckable(True)
        self.rec.toggled.connect(self._record_toggled)
        self.rec.keyDown.connect(lambda n: self.record_event(n, True))
        self.rec.keyUp.connect(lambda n: self.record_event(n, False))
        self.last_t: float | None = None
        add_key, add_delay, rm, up, down, clear = (QPushButton(t) for t in ("Add key tap", "Add delay", "Delete", "Up", "Down", "Clear"))
        add_key.clicked.connect(lambda: self._add_tap("A"))
        add_delay.clicked.connect(lambda: self._append(MacroEvent("delay", delay_ms=50)))
        rm.clicked.connect(self._delete)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        clear.clicked.connect(self._clear)
        bar = QHBoxLayout()
        for b in (self.rec, add_key, add_delay, rm, up, down, clear):
            bar.addWidget(b)
        self.mode = QComboBox()
        for text, when, rep in (("Run once when pressed", "OnPress", "NoRepeat"), ("Repeat while the button is held", "WhilePressed", "RepeatConstantly"),
                                ("Toggle repeating on / off", "Toggle", "RepeatConstantly")):
            self.mode.addItem(text, (when, rep))
        self.restart = QCheckBox("Pressing again restarts it")
        self.gap = QSpinBox(minimum=0, maximum=60000, suffix=" ms")
        self.gap.setToolTip("Pause between repeats")
        form = QFormLayout()
        form.addRow("Behaviour", self.mode)
        form.addRow("Pause between repeats", self.gap)
        form.addRow("", self.restart)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(bar)
        lay.addWidget(QLabel("Recording captures keyboard keys with their timing while you type in this window."))
        lay.addLayout(form)
        i = max(0, self.mode.findData((macro.hints.when if macro.hints.when in ("WhilePressed", "Toggle") else "OnPress", "RepeatConstantly" if macro.hints.when in ("WhilePressed", "Toggle") else "NoRepeat")))
        self.mode.setCurrentIndex(i)
        self.restart.setChecked(macro.hints.restart_on_second_exec)
        self.gap.setValue(macro.repeat.delay)
        self.refill()

    # --- table ------------------------------------------------------------------------
    @staticmethod
    def text_of(e: MacroEvent) -> tuple[str, str]:
        if e.kind == "key":
            return ("Press" if e.pressed else "Release"), " + ".join(pretty(k) for k in e.keys)
        if e.kind == "mouse":
            return ("Mouse button down" if e.pressed else "Mouse button up"), str(e.button)
        if e.delay_max_ms is not None:
            return "Random delay", f"{e.delay_ms}–{e.delay_max_ms} ms"
        return "Delay", f"{e.delay_ms} ms"

    def refill(self) -> None:
        self.table.setRowCount(0)
        for i, e in enumerate(self.macro.events):
            self.table.insertRow(i)
            a, b = self.text_of(e)
            self.table.setItem(i, 0, QTableWidgetItem(a))
            self.table.setItem(i, 1, QTableWidgetItem(b))
            if e.kind == "key":
                combo = QComboBox()
                combo.setEditable(False)
                names = sorted(n for n, t in keys.KEYS.items() if t.kind == "key" and t.code < 0x100 and n == _BY_CODE.get(t.code))
                combo.addItems(names)
                combo.setCurrentText(e.keys[0] if e.keys else "A")
                combo.currentTextChanged.connect(lambda n, ev=e: self._set_key(ev, n))
                self.table.setCellWidget(i, 1, combo)
            elif e.kind == "delay" and e.delay_max_ms is None:
                sp = QSpinBox(minimum=0, maximum=600000, suffix=" ms")
                sp.setValue(e.delay_ms)
                sp.valueChanged.connect(lambda v, ev=e: setattr(ev, "delay_ms", v))
                self.table.setCellWidget(i, 1, sp)

    def _set_key(self, e: MacroEvent, name: str) -> None:
        e.keys = (name,)
        self.table.viewport().update()

    def _append(self, e: MacroEvent) -> None:
        self.macro.events.append(e)
        self.refill()

    def _add_tap(self, name: str) -> None:
        self.macro.events += [MacroEvent("key", (name,), True), MacroEvent("delay", delay_ms=30), MacroEvent("key", (name,), False)]
        self.refill()

    def _delete(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            del self.macro.events[row]
        self.refill()

    def _move(self, d: int) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if len(rows) == 1 and 0 <= rows[0] + d < len(self.macro.events):
            r, ev = rows[0], self.macro.events
            ev[r], ev[r + d] = ev[r + d], ev[r]
            self.refill()
            self.table.selectRow(r + d)

    def _clear(self) -> None:
        self.macro.events.clear()
        self.refill()

    # --- recording ------------------------------------------------------------------------
    def _record_toggled(self, on: bool) -> None:
        self.rec.active = on
        self.rec.setText("■ Stop" if on else "● Record")
        self.last_t = None
        if on:
            self.rec.grabKeyboard()
        else:
            self.rec.releaseKeyboard()

    def record_event(self, name: str, pressed: bool, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.last_t is not None and (gap := round((now - self.last_t) * 1000)) >= 1:
            self.macro.events.append(MacroEvent("delay", delay_ms=gap))
        self.last_t = now
        self.macro.events.append(MacroEvent("key", (name,), pressed))
        self.refill()

    def apply(self) -> None:
        when, rep = self.mode.currentData()
        m = self.macro
        m.hints.when, m.repeat.mode = when, rep
        m.hints.restart_on_second_exec = self.restart.isChecked() and when == "OnPress"
        m.repeat.delay = self.gap.value()


class ActionDialog(QDialog):
    TYPES = ["Nothing", "Key or key combination", "Macro", "Type text", "DPI function", "Switch profile"]
    NOTHING, KEY, MACRO, TEXT, DPI, SWITCH = range(6)

    def __init__(self, button_label: str, current: Action | None, profiles: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Action for {button_label}")
        self.resize(640, 520)
        self.profiles, self.current = profiles, current
        self.kind = QComboBox()
        self.kind.addItems(self.TYPES)
        self.pages = QStackedWidget()
        # key
        self.capture = KeyCapture()
        self.hold = QCheckBox("Keep the key held while the button is held (otherwise it is tapped)")
        self.hold.setChecked(True)
        kp = QWidget()
        self.picker = KeyPicker()
        self.picker.added.connect(self.add_keys)
        self.picker.removedLast.connect(lambda: self.capture.set_combo(self.capture.combo[:-1]))
        self.picker.cleared.connect(lambda: self.capture.set_combo([]))
        kl = QVBoxLayout(kp)
        for w in (self.capture, self.picker, self.hold):
            kl.addWidget(w)
        kl.addStretch(1)
        # macro
        self.macro = current if isinstance(current, MacroAction) else make_action(MacroAction, "MacroAction", "Macro", events=[], termination="Interrupt", high_priority=False)
        self.macro_name = QLineEdit(self.macro.name)
        self.macro_editor = MacroEditor(self.macro)
        xp = QWidget()
        xl = QVBoxLayout(xp)
        xl.addWidget(self.macro_name)
        xl.addWidget(self.macro_editor)
        # text
        self.text = QLineEdit()
        self.text.setPlaceholderText("text to type when pressed (letters, digits and spaces)")
        tp = QWidget()
        QVBoxLayout(tp).addWidget(self.text)
        tp.layout().addStretch(1)
        # dpi
        self.dpi = QComboBox()
        for k, text in DPI_FUNCTIONS.items():
            self.dpi.addItem(text, k)
        dp = QWidget()
        QVBoxLayout(dp).addWidget(self.dpi)
        dp.layout().addStretch(1)
        # profile switch
        self.target = QComboBox()
        for p in sorted(profiles, key=lambda p: p.name.lower()):
            self.target.addItem(p.name, p.id)
        sp = QWidget()
        QVBoxLayout(sp).addWidget(self.target)
        sp.layout().addStretch(1)
        for w in (QWidget(), kp, xp, tp, dp, sp):
            self.pages.addWidget(w)
        self.kind.currentIndexChanged.connect(self.pages.setCurrentIndex)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("When the button is pressed:"))
        lay.addWidget(self.kind)
        lay.addWidget(self.pages, 1)
        lay.addWidget(buttons)
        self._prefill()

    def add_keys(self, names: list[str]) -> None:
        combo = self.capture.combo + [n for n in names if n not in self.capture.combo]
        self.capture.set_combo(combo)
        if combo and all(k in MEDIA_KEYS for k in combo):
            self.hold.setChecked(False)  # media keys are tapped: holding one would auto-repeat it

    def _prefill(self) -> None:
        a = self.current
        index = self.NOTHING
        if isinstance(a, KeyRemapAction):
            if a.key in DPI_FUNCTIONS:
                index = self.DPI
                self.dpi.setCurrentIndex(self.dpi.findData(a.key))
            else:
                index = self.KEY
                self.capture.set_combo([a.key] if a.key else list(a.keystroke))
                self.hold.setChecked(a.hints.when != "OnPress")
        elif isinstance(a, MediaAction):  # media is now just a key: it shows (and saves) as one
            index = self.KEY
            self.capture.set_combo([MEDIA_AS_KEY.get(a.media, a.media)])
            self.hold.setChecked(False)
        elif isinstance(a, MacroAction):
            index = self.MACRO
        elif isinstance(a, TextAction):
            index = self.TEXT
            self.text.setText(a.text)
        elif isinstance(a, ProfileSwitchAction):
            index = self.SWITCH
            self.target.setCurrentIndex(max(0, self.target.findData(a.target)))
        self.kind.setCurrentIndex(index)

    def result_action(self) -> Action | None:
        i = self.kind.currentIndex()
        if i == self.KEY and self.capture.combo:
            c = self.capture.combo
            return make_action(KeyRemapAction, "KeyRemapAction", "Key", "OnBoth" if self.hold.isChecked() else "OnPress", key="", keystroke=tuple(c))
        if i == self.MACRO and self.macro.events:
            self.macro.name = self.macro_name.text() or "Macro"
            self.macro_editor.apply()
            return self.macro
        if i == self.TEXT and self.text.text():
            return make_action(TextAction, "TextAction", "Text", text=self.text.text(), char_delay_ms=0)
        if i == self.DPI:
            return make_action(KeyRemapAction, "KeyRemapAction", "DPI", "OnBoth", key=self.dpi.currentData(), keystroke=())
        if i == self.SWITCH and self.target.currentData():
            return make_action(ProfileSwitchAction, "ProfileSwitchingAction", "Switch profile", switch_type="Direct",
                               target=self.target.currentData(), targets=(), direction="Forward", loop=True)
        return None


class ButtonsTab(QWidget):
    changed = Signal()

    def __init__(self, all_profiles):
        super().__init__()
        self.profile = None
        self.all_profiles = all_profiles  # callable -> current list of profiles
        self.table = QTableWidget(len(BUTTONS), 3)
        self.table.setHorizontalHeaderLabels(["Button", "Does", ""])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 420)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, (button, label) in enumerate(BUTTONS):  # rows are built once; refill() only updates the text
            self.table.setItem(r, 0, QTableWidgetItem(label))
            self.table.setItem(r, 1, QTableWidgetItem(""))
            edit, clear = QPushButton("Edit…"), QPushButton("Clear")
            edit.clicked.connect(lambda _, bt=button, lb=label: self.edit(bt, lb))
            clear.clicked.connect(lambda _, bt=button: self.set_action(bt, None))
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(2, 0, 2, 0)
            row.addWidget(edit)
            row.addWidget(clear)
            self.table.setCellWidget(r, 2, cell)
        note = QLabel("Buttons you leave empty do nothing, except the DPI button, which cycles your DPI stages.")
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.table)

    def set_profile(self, profile) -> None:
        self.profile = profile
        self.setEnabled(profile is not None and profile.mouse is not None)
        self.refill()

    def binding(self, button: str) -> Binding | None:
        return self.profile.mouse.binding(button) if self.profile and self.profile.mouse else None

    def refill(self) -> None:
        profiles = self.all_profiles()
        for r, (button, _) in enumerate(BUTTONS):
            b = self.binding(button)
            self.table.item(r, 1).setText(describe(b.action if b else None, profiles))

    def edit(self, button: str, label: str) -> None:
        b = self.binding(button)
        dlg = ActionDialog(label, b.action if b else None, self.all_profiles(), self)
        if dlg.exec() == QDialog.Accepted:
            self.set_action(button, dlg.result_action())

    def set_action(self, button: str, action: Action | None) -> None:
        bindings = self.profile.mouse.bindings
        bindings[:] = [x for x in bindings if x.button != button]
        if action is not None:
            bindings.append(Binding(button, action))
        self.refill()
        self.changed.emit()
