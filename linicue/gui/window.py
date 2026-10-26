"""Main window: profile list on the left, editors in tabs on the right. Edits autosave (like iCUE)."""
from __future__ import annotations

import copy
import sys
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import store
from ..lighting import ZONES
from ..profile import Color, Effect, LightingLayer, MouseSettings, Profile
from .links_tab import LinksTab

SAVE_DELAY_MS = 500


def new_profile(name: str, dpi_ref: str = "") -> Profile:
    white = Effect("StaticLighting", 1000, 10, [(0.0, Color(1, 1, 1))])
    layer = LightingLayer("Static 1", "{%s}" % uuid.uuid4(), tuple(ZONES), True, white)
    return Profile("{%s}" % uuid.uuid4(), name, [], MouseSettings([], [layer], dpi_ref=dpi_ref))


def duplicate(p: Profile) -> Profile:
    q = store.profile_from_dict(store.profile_to_dict(p))
    q.id, q.name, q.is_initial, q.path = "{%s}" % uuid.uuid4(), p.name + " copy", False, None
    return q


class Daemon:
    """Talks to the running daemon over D-Bus (preview a profile on the mouse); everything is optional."""

    def __init__(self):
        self.iface = None
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface
            iface = QDBusInterface("org.linicue.Daemon", "/org/linicue/Daemon", "org.linicue.Daemon", QDBusConnection.sessionBus())
            self.iface = iface if iface.isValid() else None
        except ImportError:
            pass

    @property
    def connected(self) -> bool:
        return self.iface is not None

    def force(self, profile_id: str) -> None:
        if self.iface:
            self.iface.call("ForceProfile", profile_id)


class MainWindow(QMainWindow):
    def __init__(self, root=store.CONFIG_DIR):
        super().__init__()
        self.root = root
        self.setWindowTitle("linicue")
        self.resize(1100, 720)
        self.profiles, _ = store.load_store(root)
        self.presets = store.load_raw_presets(root)
        self.settings = store.load_settings(root)
        self.current: Profile | None = None
        self.daemon = Daemon()
        self.saver = QTimer(singleShot=True, interval=SAVE_DELAY_MS)
        self.saver.timeout.connect(self.save_now)

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._renamed)
        buttons = QHBoxLayout()
        for text, fn in (("New", self._new), ("Duplicate", self._duplicate), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        imp = QPushButton("Import from iCUE…")
        imp.clicked.connect(self._import)
        default = QPushButton("Use as default profile")
        default.setToolTip("The profile used when no linked program has focus")
        default.clicked.connect(self._make_default)
        self.preview = QCheckBox("Show on mouse")
        self.preview.setToolTip("Pin this profile on the mouse so you can see lighting changes live")
        self.preview.toggled.connect(self._preview_toggled)
        self.status = QLabel()
        left = QWidget()
        lv = QVBoxLayout(left)
        for w in (QLabel("Profiles"), self.list):
            lv.addWidget(w)
        lv.addLayout(buttons)
        for w in (default, imp, self.preview, self.status):
            lv.addWidget(w)

        self.tabs = QTabWidget()
        self.links = LinksTab()
        self.editors = [("App links", self.links)]
        self._add_optional_tabs()
        for name, w in self.editors:
            self.tabs.addTab(w, name)
            w.changed.connect(self.touch)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self._fill_list()
        self._refresh_status()

    def _add_optional_tabs(self) -> None:
        from .lighting_tab import LightingTab
        self.lighting = LightingTab()
        self.editors.insert(0, ("Lighting", self.lighting))
        from .dpi_tab import DpiTab
        self.dpi = DpiTab(self.presets)
        self.dpi.presetsChanged.connect(self.touch_presets)
        self.editors.insert(1, ("DPI", self.dpi))
        from .mouse_tab import MouseTab
        self.mouse = MouseTab(self.settings)
        self.mouse.settingsChanged.connect(self.touch_settings)
        self.editors.insert(2, ("Mouse", self.mouse))
        from .buttons_tab import ButtonsTab
        self.buttons = ButtonsTab(lambda: self.profiles)
        self.editors.insert(0, ("Buttons", self.buttons))

    # --- list -----------------------------------------------------------------
    def _fill_list(self, select: Profile | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for p in sorted(self.profiles, key=lambda p: (not p.is_initial, p.name.lower())):
            item = QListWidgetItem(("★ " if p.is_initial else "") + p.name)
            item.setData(Qt.UserRole, p.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.list.addItem(item)
        self.list.blockSignals(False)
        target = select or self.current
        for i in range(self.list.count()):
            if target and self.list.item(i).data(Qt.UserRole) == target.id:
                self.list.setCurrentRow(i)
                return
        # nothing chosen (startup, or the selected profile was deleted): the list is sorted default-first
        self.list.setCurrentRow(0) if self.list.count() else self._select(-1)

    def _select(self, row: int) -> None:
        self.save_now()
        pid = self.list.item(row).data(Qt.UserRole) if row >= 0 else None
        self.current = next((p for p in self.profiles if p.id == pid), None)
        for _, w in self.editors:
            w.set_profile(self.current)
        if self.preview.isChecked():
            self.daemon.force(pid or "")

    def _renamed(self, item: QListWidgetItem) -> None:
        p = next((p for p in self.profiles if p.id == item.data(Qt.UserRole)), None)
        if p:
            p.name = item.text().lstrip("★ ").strip() or p.name
            store.save_profile(p, self.root)  # it may not be the selected profile, so save it directly

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Name:")
        if ok and name.strip():
            ref = next(iter(self.presets), "")
            p = new_profile(name.strip(), ref)
            self.profiles.append(p)
            store.save_profile(p, self.root)
            self._fill_list(p)

    def _duplicate(self) -> None:
        if self.current:
            p = duplicate(self.current)
            self.profiles.append(p)
            store.save_profile(p, self.root)
            self._fill_list(p)

    def _delete(self) -> None:
        p = self.current
        if p and QMessageBox.question(self, "Delete profile", f"Delete “{p.name}”? This cannot be undone.") == QMessageBox.Yes:
            self.saver.stop()
            store.delete_profile(p, self.root)
            self.profiles.remove(p)
            self.current = None
            self._fill_list()

    def _make_default(self) -> None:
        if self.current:
            for p in self.profiles:
                p.is_initial = p is self.current
                store.save_profile(p, self.root)
            self._fill_list(self.current)

    def _import(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose iCUE's profiles folder")
        if folder:
            n = store.import_icue(folder, self.root)
            self.profiles, _ = store.load_store(self.root)
            self.presets.clear()
            self.presets.update(store.load_raw_presets(self.root))  # in place: the DPI tab shares this dict
            self.current = None
            self._fill_list()
            QMessageBox.information(self, "Import", f"Imported {n} profiles.")

    # --- saving / daemon ---------------------------------------------------------
    def touch(self) -> None:
        self.saver.start()

    def touch_settings(self) -> None:
        self.settings_dirty = True
        self.saver.start()

    def touch_presets(self) -> None:
        self.presets_dirty = True
        self.saver.start()

    def save_now(self) -> None:
        if self.saver.isActive():
            self.saver.stop()
        if self.current:
            store.save_profile(self.current, self.root)
        if getattr(self, "presets_dirty", False):
            store.save_presets(self.presets, self.root)
            self.presets_dirty = False
        if getattr(self, "settings_dirty", False):
            store.save_settings(self.settings, self.root)
            self.settings_dirty = False

    def _preview_toggled(self, on: bool) -> None:
        self.save_now()
        self.daemon.force(self.current.id if on and self.current else "")
        self._refresh_status()

    def _refresh_status(self) -> None:
        if not self.daemon.connected:
            self.status.setText("daemon: not running (preview off)")
        elif self.preview.isChecked():  # a pin silently stops window-based switching, so say so
            self.status.setText("daemon: connected. PINNED: this profile stays on the mouse and automatic switching is paused")
        else:
            self.status.setText("daemon: connected")
        self.status.setWordWrap(True)
        self.preview.setEnabled(self.daemon.connected)

    def closeEvent(self, e) -> None:
        self.save_now()
        self.daemon.force("")  # never leave a profile pinned
        super().closeEvent(e)


def configure_app(app: QApplication) -> None:
    """Identify the app to the desktop. On Wayland the window's id must equal the .desktop file's name, or Plasma
    cannot find the icon (it shows a generic one) and does not group the window with its launcher."""
    app.setApplicationName("linicue")
    app.setDesktopFileName("linicue")
    app.setWindowIcon(QIcon.fromTheme("input-mouse"))


def main() -> int:
    app = QApplication(sys.argv)
    configure_app(app)
    w = MainWindow()
    w.show()
    return app.exec()
