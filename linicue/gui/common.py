from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton

from ..profile import Color


def qcolor(c: Color) -> QColor:
    return QColor.fromRgbF(*(max(0.0, min(1.0, v)) for v in (c.r, c.g, c.b)))


def color_of(q: QColor) -> Color:
    return Color(q.redF(), q.greenF(), q.blueF())


class ColorButton(QPushButton):
    """A swatch that opens a colour picker; emits colorChanged(Color)."""
    colorChanged = Signal(object)

    def __init__(self, color: Color = Color(1, 1, 1)):
        super().__init__()
        self.setFixedWidth(64)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: Color) -> None:
        self._color = color
        q = qcolor(color)
        self.setStyleSheet(f"background-color: {q.name()}; border: 1px solid #888; min-height: 20px;")

    def color(self) -> Color:
        return self._color

    def _pick(self) -> None:
        q = QColorDialog.getColor(qcolor(self._color), self, "Pick a colour")
        if q.isValid():
            self.set_color(color_of(q))
            self.colorChanged.emit(self._color)
