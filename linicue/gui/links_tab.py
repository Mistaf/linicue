"""Which programs/windows switch to this profile."""
from __future__ import annotations

import ntpath

from PySide6.QtCore import Qt, Signal

from ..steam import installdir_from_path
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)


def label(entry: str) -> str:
    """Friendly list text for a stored entry: the program name, plus the Steam folder when there is one."""
    name = ntpath.basename(entry.replace("/", "\\")) or entry
    game = installdir_from_path(entry)
    return f"{name}   (Steam: {game})" if game else name


class LinksTab(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.profile = None
        self.list = QListWidget()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("program name or window class, e.g. firefox, Rust.exe")
        add, browse, remove = QPushButton("Add"), QPushButton("Browse…"), QPushButton("Remove selected")
        add.clicked.connect(self._add)
        self.entry.returnPressed.connect(self._add)
        browse.clicked.connect(self._browse)
        remove.clicked.connect(self._remove)
        row = QHBoxLayout()
        for w in (self.entry, add, browse):
            row.addWidget(w)
        note = QLabel("This profile becomes active while one of these programs has focus. Add each program you use by its "
                      "name, e.g. Discord.exe for the Windows program or the name of its Linux counterpart; a Steam game's .exe "
                      "works too. The daemon matches the name against the window's class, desktop file and process. "
                      "Leave the list empty to only select the profile by hand.")
        note.setWordWrap(True)
        lay = QVBoxLayout(self)
        for w in (note, self.list):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addWidget(remove)

    def set_profile(self, profile) -> None:
        self.profile = profile
        self.list.clear()
        for entry in (profile.linked_programs if profile else []):
            self._item(entry)
        self.setEnabled(profile is not None)

    def _item(self, entry: str) -> None:
        item = QListWidgetItem(label(entry))
        item.setData(Qt.UserRole, entry)
        item.setToolTip(entry)
        self.list.addItem(item)

    def _add(self, text: str | None = None) -> None:
        text = (text if isinstance(text, str) else self.entry.text()).strip()
        if text and text not in self.profile.linked_programs:
            self.profile.linked_programs.append(text)
            self._item(text)
            self.entry.clear()
            self.changed.emit()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the program")
        if path:
            self._add(ntpath.basename(path.replace("/", "\\")))

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.profile.linked_programs.remove(item.data(Qt.UserRole))
            self.list.takeItem(self.list.row(item))
        self.changed.emit()
