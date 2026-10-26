"""DPI editor: five stages and the sniper stage (shared by all profiles through the preset)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ..profile import Color
from .common import ColorButton

STAGES = ["1", "2", "3", "4", "5", "sniper"]


class DpiTab(QWidget):
    """Edits the raw preset dicts (the same structure dpi.json stores); the window saves them."""
    changed = Signal()
    presetsChanged = Signal()

    def __init__(self, presets: dict[str, dict]):
        super().__init__()
        self.presets, self.profile, self.loading = presets, None, False
        self.which = QComboBox()
        self.which.activated.connect(self._pick_preset)
        self.name = QLineEdit()
        self.name.textEdited.connect(self._name_edited)
        new = QPushButton("New preset")
        new.clicked.connect(self._new_preset)
        grid = QGridLayout()
        for c, h in enumerate(("Stage", "On", "DPI", "Separate Y", "DPI Y", "Light colour")):
            grid.addWidget(QLabel(f"<b>{h}</b>"), 0, c)
        self.rows: dict[str, dict] = {}
        for r, key in enumerate(STAGES, 1):
            w = {"on": QCheckBox(), "x": QSpinBox(minimum=100, maximum=26000, singleStep=50), "sep": QCheckBox(),
                 "y": QSpinBox(minimum=100, maximum=26000, singleStep=50), "color": ColorButton()}
            w["y"].setEnabled(False)
            w["on"].toggled.connect(lambda v, k=key: self._edit(k, enabled=v))
            w["x"].valueChanged.connect(lambda v, k=key: self._edit(k, x=v))
            w["sep"].toggled.connect(lambda v, k=key: self._edit(k, sep=v))
            w["y"].valueChanged.connect(lambda v, k=key: self._edit(k, y=v))
            w["color"].colorChanged.connect(lambda c, k=key: self._edit(k, color=[round(c.r * 255), round(c.g * 255), round(c.b * 255)]))
            label = QLabel("Sniper (while the sniper button is held)" if key == "sniper" else f"Stage {key}")
            for c, widget in enumerate((label, w["on"], w["x"], w["sep"], w["y"], w["color"])):
                grid.addWidget(widget, r, c)
            self.rows[key] = w
        self.default = QComboBox()
        self.default.addItems([f"Stage {i}" for i in range(1, 6)])
        self.default.activated.connect(self._default_edited)
        note = QLabel("The DPI button cycles the enabled stages. The DPI light shows the colour of the active stage. "
                      "Tick “Separate Y” only if you want a different vertical DPI. "
                      "Changes apply when the daemon reloads (a second after saving).")
        note.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("DPI preset used by this profile:"))
        lay.addWidget(self.which)
        lay.addWidget(self.name)
        lay.addWidget(new)
        lay.addLayout(grid)
        lay.addWidget(QLabel("Starts on:"))
        lay.addWidget(self.default)
        lay.addWidget(note)
        lay.addStretch(1)

    def set_profile(self, profile) -> None:
        self.profile = profile
        self.setEnabled(profile is not None and bool(self.presets))
        self.refill()

    def refill(self) -> None:
        self.loading = True
        self.which.clear()
        for pid, p in self.presets.items():
            self.which.addItem(p.get("name") or "(unnamed)", pid)
        ref = self.profile.mouse.dpi_ref if self.profile and self.profile.mouse else ""
        i = self.which.findData(ref)
        self.which.setCurrentIndex(max(0, i))
        self._load(self.which.currentData())
        self.loading = False

    def _stage(self, key: str) -> dict | None:
        p = self.presets.get(self.which.currentData()) or {}
        return p.get("sniper") if key == "sniper" else p.get("stages", {}).get(key)

    def _load(self, pid) -> None:
        p = self.presets.get(pid)
        self.name.setText(p.get("name", "") if p else "")
        for key, w in self.rows.items():
            st = self._stage(key)
            if st:
                x, y = st["dpi"]
                w["on"].setChecked(st["enabled"])
                w["x"].setValue(x)
                w["y"].setValue(y)
                w["sep"].setChecked(x != y)
                w["y"].setEnabled(x != y)
                w["color"].set_color(Color(*(c / 255 for c in st["color"])))
        self.default.setCurrentIndex(int((p or {}).get("default", 1)) - 1)

    @property
    def preset(self) -> dict | None:
        return self.presets.get(self.which.currentData())

    def _pick_preset(self, _=None) -> None:
        pid = self.which.currentData()
        if self.profile and self.profile.mouse and pid:
            self.profile.mouse.dpi_ref = pid
            self.loading = True
            self._load(pid)
            self.loading = False
            self.changed.emit()

    def _edit(self, key: str, **change) -> None:
        """One stage widget changed. Y follows X unless “Separate Y” is ticked."""
        st = self._stage(key)
        if self.loading or st is None:
            return
        w = self.rows[key]
        x, y = st["dpi"]
        if "x" in change:
            x = change["x"]
            y = y if w["sep"].isChecked() else x
        if "y" in change:
            y = change["y"]
        if "sep" in change:
            w["y"].setEnabled(change["sep"])
            if not change["sep"]:
                y = x
        st["dpi"] = [x, y]
        if w["y"].value() != y:
            self.loading = True
            w["y"].setValue(y)
            self.loading = False
        for field in ("enabled", "color"):
            if field in change:
                st[field] = change[field]
        self.presetsChanged.emit()

    def _default_edited(self, i: int) -> None:
        if self.preset:
            self.preset["default"] = i + 1
            self.presetsChanged.emit()

    def _name_edited(self, text: str) -> None:
        if self.preset and not self.loading:
            self.preset["name"] = text
            self.which.setItemText(self.which.currentIndex(), text or "(unnamed)")
            self.presetsChanged.emit()

    def _new_preset(self) -> None:
        import copy
        import uuid
        base = copy.deepcopy(self.preset) if self.preset else {
            "default": 2, "stages": {str(i): {"dpi": [800 * i, 800 * i], "enabled": i <= 3, "color": [255, 255, 255]} for i in range(1, 6)},
            "sniper": {"dpi": [400, 400], "enabled": True, "color": [255, 255, 0]}}
        base["name"] = (base.get("name") or "Preset") + " copy"
        pid = "{%s}" % uuid.uuid4()
        self.presets[pid] = base
        if self.profile and self.profile.mouse:
            self.profile.mouse.dpi_ref = pid
        self.refill()
        self.presetsChanged.emit()
        self.changed.emit()
