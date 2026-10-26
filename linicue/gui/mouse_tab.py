"""Mouse settings: angle snapping (per profile) and polling rate (the whole device)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

RATES = [("Leave as it is", None), ("125 Hz (8 ms)", 125), ("250 Hz (4 ms)", 250), ("500 Hz (2 ms)", 500), ("1000 Hz (1 ms)", 1000)]


class MouseTab(QWidget):
    changed = Signal()          # the selected profile was edited
    settingsChanged = Signal()  # a device-wide setting was edited

    def __init__(self, settings: dict):
        super().__init__()
        self.settings, self.profile, self.loading = settings, None, False
        self.snap = QCheckBox("Angle snapping")
        self.snap.setToolTip("Smooths small wobbles so straight lines come out straighter")
        self.snap.toggled.connect(self._snap_edited)
        self.rate = QComboBox()
        for text, hz in RATES:
            self.rate.addItem(text, hz)
        self.rate.activated.connect(self._rate_edited)
        profile_box = QGroupBox("This profile")
        QVBoxLayout(profile_box).addWidget(self.snap)
        device_box = QGroupBox("The mouse (all profiles)")
        form = QFormLayout(device_box)
        form.addRow("Polling rate", self.rate)
        note = QLabel("Changing the polling rate makes the mouse reconnect for a moment. “Leave as it is” never writes it, "
                      "so the mouse keeps whatever it has now.")
        note.setWordWrap(True)
        form.addRow(note)
        lay = QVBoxLayout(self)
        lay.addWidget(profile_box)
        lay.addWidget(device_box)
        lay.addStretch(1)
        self.refill()

    def set_profile(self, profile) -> None:
        self.profile = profile
        self.snap.setEnabled(profile is not None and profile.mouse is not None)
        self.refill()

    def refill(self) -> None:
        self.loading = True
        m = self.profile.mouse if self.profile else None
        self.snap.setChecked(bool(m and m.angle_snapping))
        self.rate.setCurrentIndex(max(0, self.rate.findData(self.settings.get("polling_rate_hz"))))
        self.loading = False

    def _snap_edited(self, on: bool) -> None:
        if not self.loading and self.profile and self.profile.mouse:
            self.profile.mouse.angle_snapping = on
            if not self.profile.mouse.angle_snapping_value:
                self.profile.mouse.angle_snapping_value = 5  # iCUE's default angle
            self.changed.emit()

    def _rate_edited(self, _=None) -> None:
        hz = self.rate.currentData()
        if hz is None:
            self.settings.pop("polling_rate_hz", None)
        else:
            self.settings["polling_rate_hz"] = hz
        self.settingsChanged.emit()
