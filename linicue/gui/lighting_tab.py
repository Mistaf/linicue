"""Lighting editor: layers (first = on top), per-layer LEDs and effect, with a live preview of the five zones."""
from __future__ import annotations

import time
import uuid

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSlider, QSpinBox, QTableWidget, QVBoxLayout, QWidget)

from ..lighting import ZONES, effect_color, render
from ..profile import Color, Effect, LightingLayer
from .common import ColorButton, color_of, qcolor

LED_NAMES = {"MouseFrontLed": "Front", "MouseLogoLed": "Logo", "MouseDpiLed": "DPI", "MouseScrollLed": "Scroll", "MouseSideLed": "Side"}
KINDS = {"StaticLighting": "Static colour", "GradientLighting": "Gradient (loops)", "TemperatureLighting": "Temperature (CPU)"}
TEMP_DEFAULT = [(0.0, Color(0, 1, 0)), (50.0, Color(0, 1, 0)), (60.0, Color(1, 1, 0)), (80.0, Color(1, 0, 0))]


def new_effect(kind: str) -> Effect:
    if kind == "StaticLighting":
        return Effect(kind, 1000, 10, [(0.0, Color(1, 1, 1))])
    if kind == "GradientLighting":
        return Effect(kind, 5000, 10, [(0.0, Color(0, 0.6, 1)), (0.5, Color(1, 0.2, 0.8)), (1.0, Color(0, 0.6, 1))])
    return Effect(kind, 1000, 10, list(TEMP_DEFAULT), {})


class MousePreview(QWidget):
    """The five zones as lamps, animated from the layers."""

    def __init__(self):
        super().__init__()
        self.layers: list[LightingLayer] = []
        self.frame: dict[int, tuple[int, int, int]] = {}
        self.t0 = time.monotonic()
        self.setMinimumHeight(110)
        timer = QTimer(self, interval=60)
        timer.timeout.connect(self._tick)
        timer.start()

    def set_layers(self, layers: list[LightingLayer]) -> None:
        self.layers = layers
        self._tick()

    def _tick(self) -> None:
        self.frame = render(self.layers, (time.monotonic() - self.t0) * 1000, 40)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        slot = w / len(ZONES)
        for i, (led, zone) in enumerate(ZONES.items()):
            r, g, b = self.frame.get(zone, (0, 0, 0))
            cx, cy = slot * (i + 0.5), h * 0.42
            glow = QColor(r, g, b)
            p.setPen(QPen(QColor(120, 120, 120), 1.5))
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(cx - 22, cy - 22, 44, 44))
            p.setPen(self.palette().text().color())
            p.drawText(QRectF(cx - slot / 2, cy + 28, slot, 20), Qt.AlignCenter, LED_NAMES[led])


class GradientBar(QWidget):
    """Shows the colour stops of the selected effect."""

    def __init__(self):
        super().__init__()
        self.stops: list[tuple[float, Color]] = []
        self.span = 1.0
        self.setFixedHeight(22)

    def set_stops(self, stops, span: float) -> None:
        self.stops, self.span = stops, span
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        if not self.stops:
            return
        g = QLinearGradient(0, 0, self.width(), 0)
        for t, c in self.stops:
            g.setColorAt(max(0.0, min(1.0, t / self.span)), qcolor(c))
        p.fillRect(self.rect(), QBrush(g))
        p.setPen(QColor(120, 120, 120))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


class LightingTab(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.profile = None
        self.layer: LightingLayer | None = None
        self.loading = False
        self.preview = MousePreview()

        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.model().rowsMoved.connect(self._reordered)
        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._toggled)
        add = QPushButton("Add layer")
        menu = QMenu(add)
        for kind, text in KINDS.items():
            menu.addAction(text, lambda k=kind: self._add(k))
        add.setMenu(menu)
        rm = QPushButton("Remove")
        rm.clicked.connect(self._remove)
        up, down = QPushButton("Up"), QPushButton("Down")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        row = QHBoxLayout()
        for b in (add, rm, up, down):
            row.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(QLabel("Layers (the top one wins where layers overlap)"))
        left.addWidget(self.list)
        left.addLayout(row)

        self.name = QLineEdit()
        self.name.textEdited.connect(self._name_edited)
        self.leds = {led: QCheckBox(text) for led, text in LED_NAMES.items()}
        leds = QHBoxLayout()
        for led, cb in self.leds.items():
            cb.toggled.connect(self._leds_edited)
            leds.addWidget(cb)
        self.kind = QComboBox()
        for kind, text in KINDS.items():
            self.kind.addItem(text, kind)
        self.kind.activated.connect(self._kind_edited)
        self.brightness = QSlider(Qt.Horizontal, minimum=0, maximum=10)
        self.brightness.valueChanged.connect(self._brightness_edited)
        self.brightness_text = QLabel("10")
        self.brightness.valueChanged.connect(lambda v: self.brightness_text.setText(str(v)))
        brightness_row = QHBoxLayout()
        brightness_row.addWidget(self.brightness)
        brightness_row.addWidget(self.brightness_text)
        self.duration = QSpinBox(minimum=100, maximum=600000, singleStep=100, suffix=" ms")
        self.duration.valueChanged.connect(self._duration_edited)
        self.bar = GradientBar()
        self.stops = QTableWidget(0, 3)
        self.stops.setHorizontalHeaderLabels(["Position", "Colour", ""])
        self.stops.verticalHeader().hide()
        self.stops.setColumnWidth(0, 110)
        self.stops.horizontalHeader().setStretchLastSection(True)
        add_stop = QPushButton("Add colour stop")
        add_stop.clicked.connect(self._add_stop)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("LEDs", leds)
        form.addRow("Effect", self.kind)
        form.addRow("Brightness (0-10)", brightness_row)
        self.duration_label = QLabel("Loop length")
        form.addRow(self.duration_label, self.duration)
        box = QGroupBox("Selected layer")
        bl = QVBoxLayout(box)
        bl.addLayout(form)
        bl.addWidget(self.bar)
        bl.addWidget(self.stops)
        bl.addWidget(add_stop)
        bl.addStretch(1)
        self.editor = box

        cols = QHBoxLayout()
        lw = QWidget()
        lw.setLayout(left)
        cols.addWidget(lw, 2)
        cols.addWidget(box, 3)
        lay = QVBoxLayout(self)
        lay.addWidget(self.preview)
        lay.addLayout(cols)

    # --- model <-> widgets ------------------------------------------------------
    def set_profile(self, profile) -> None:
        self.profile = profile
        self.setEnabled(profile is not None)
        self._fill_list()

    @property
    def layers(self) -> list[LightingLayer]:
        return self.profile.mouse.lighting if self.profile and self.profile.mouse else []

    def _fill_list(self, select: int = 0) -> None:
        self.loading = True
        self.list.clear()
        for l in self.layers:
            item = QListWidgetItem(l.name or "(unnamed)")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if l.enabled else Qt.Unchecked)
            self.list.addItem(item)
        self.loading = False
        self.preview.set_layers(self.layers)
        if self.layers:
            self.list.setCurrentRow(min(select, len(self.layers) - 1))
        else:
            self._select(-1)

    def _select(self, row: int) -> None:
        self.layer = self.layers[row] if 0 <= row < len(self.layers) else None
        self.editor.setEnabled(self.layer is not None)
        if not self.layer:
            return
        self.loading = True
        l, e = self.layer, self.layer.effect
        self.name.setText(l.name)
        for led, cb in self.leds.items():
            cb.setChecked(led in l.leds)
        self.kind.setCurrentIndex(max(0, self.kind.findData(e.kind)) if e else 0)
        self.brightness.setValue(e.brightness if e else 10)
        self.duration.setValue(e.duration_ms if e else 1000)
        gradient = bool(e and e.kind == "GradientLighting")
        self.duration.setVisible(gradient)
        self.duration_label.setVisible(gradient)
        self._fill_stops()
        self.loading = False

    def _fill_stops(self) -> None:
        e = self.layer.effect
        temp = e.kind == "TemperatureLighting"
        static = e.kind == "StaticLighting"
        self.stops.setRowCount(0)
        self.stops.setHorizontalHeaderLabels(["Temperature" if temp else "Position", "Colour", ""])
        for i, (t, c) in enumerate(e.stops):
            self.stops.insertRow(i)
            if static:
                self.stops.setCellWidget(i, 0, QLabel("always"))
            else:
                sp = QSpinBox(minimum=0, maximum=100, suffix=" °C" if temp else " %")
                sp.setValue(round(t if temp else t * 100))
                sp.valueChanged.connect(lambda v, i=i: self._stop_pos(i, v))
                self.stops.setCellWidget(i, 0, sp)
            cb = ColorButton(c)
            cb.colorChanged.connect(lambda col, i=i: self._stop_color(i, col))
            self.stops.setCellWidget(i, 1, cb)
            if not static and len(e.stops) > 2:
                rm = QPushButton("Remove")
                rm.clicked.connect(lambda _, i=i: self._del_stop(i))
                self.stops.setCellWidget(i, 2, rm)
        self.bar.set_stops(e.stops, 80.0 if temp else 1.0)
        self.stops.setMaximumHeight(60 + 34 * len(e.stops))

    def _edited(self, refresh_stops: bool = False) -> None:
        self.preview.set_layers(self.layers)
        if refresh_stops and self.layer and self.layer.effect:
            self.bar.set_stops(self.layer.effect.stops, 80.0 if self.layer.effect.kind == "TemperatureLighting" else 1.0)
        self.changed.emit()

    # --- list actions ---------------------------------------------------------------
    def _add(self, kind: str) -> None:
        n = sum(1 for l in self.layers if l.effect and l.effect.kind == kind) + 1
        layer = LightingLayer(f"{KINDS[kind].split(' (')[0]} {n}", "{%s}" % uuid.uuid4(), tuple(ZONES), True, new_effect(kind))
        self.layers.insert(0, layer)  # new layers go on top
        self._fill_list(0)
        self.changed.emit()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.layers):
            del self.layers[row]
            self._fill_list(row)
            self.changed.emit()

    def _move(self, delta: int) -> None:
        row, new = self.list.currentRow(), self.list.currentRow() + delta
        if 0 <= row < len(self.layers) and 0 <= new < len(self.layers):
            self.layers[row], self.layers[new] = self.layers[new], self.layers[row]
            self._fill_list(new)
            self.changed.emit()

    def _reordered(self, *_) -> None:
        if self.loading:
            return
        order = [self.list.item(i).text() for i in range(self.list.count())]
        by_name = {}
        for l in self.layers:
            by_name.setdefault(l.name or "(unnamed)", []).append(l)
        self.profile.mouse.lighting[:] = [by_name[n].pop(0) for n in order]
        self._edited()

    def _toggled(self, item: QListWidgetItem) -> None:
        if not self.loading:
            self.layers[self.list.row(item)].enabled = item.checkState() == Qt.Checked
            self._edited()

    # --- layer edits --------------------------------------------------------------------
    def _name_edited(self, text: str) -> None:
        if self.layer and not self.loading:
            self.layer.name = text
            self.list.item(self.list.currentRow()).setText(text or "(unnamed)")
            self.changed.emit()

    def _leds_edited(self) -> None:
        if self.layer and not self.loading:
            self.layer.leds = tuple(led for led, cb in self.leds.items() if cb.isChecked())
            self._edited()

    def _kind_edited(self, _) -> None:
        kind = self.kind.currentData()
        if self.layer and not self.loading and (not self.layer.effect or self.layer.effect.kind != kind):
            old = self.layer.effect
            fresh = new_effect(kind)
            if old and kind != "TemperatureLighting" and old.kind != "TemperatureLighting":
                fresh.stops = old.stops[:1] if kind == "StaticLighting" else (old.stops if len(old.stops) > 1 else old.stops * 2)
                if kind == "GradientLighting" and len(fresh.stops) == 2 and fresh.stops[0][0] == fresh.stops[1][0]:
                    fresh.stops = [(0.0, fresh.stops[0][1]), (1.0, fresh.stops[1][1])]
            fresh.brightness = old.brightness if old else 10
            self.layer.effect = fresh
            self._select(self.list.currentRow())
            self._edited()

    def _brightness_edited(self, v: int) -> None:
        if self.layer and self.layer.effect and not self.loading:
            self.layer.effect.brightness = v
            self._edited()

    def _duration_edited(self, v: int) -> None:
        if self.layer and self.layer.effect and not self.loading:
            self.layer.effect.duration_ms = v
            self._edited()

    def _stop_color(self, i: int, color: Color) -> None:
        e = self.layer.effect
        e.stops[i] = (e.stops[i][0], color)
        self._edited(True)

    def _stop_pos(self, i: int, v: int) -> None:
        e = self.layer.effect
        e.stops[i] = (float(v) if e.kind == "TemperatureLighting" else v / 100, e.stops[i][1])
        e.stops.sort(key=lambda s: s[0])
        self._edited(True)

    def _add_stop(self) -> None:
        e = self.layer.effect
        if e.kind == "StaticLighting":
            return
        last_t, last_c = e.stops[-1]
        e.stops.append((min(last_t + (10.0 if e.kind == "TemperatureLighting" else 0.1), 100.0 if e.kind == "TemperatureLighting" else 1.0), last_c))
        self._fill_stops()
        self._edited()

    def _del_stop(self, i: int) -> None:
        e = self.layer.effect
        if len(e.stops) > 2:
            del e.stops[i]
            self._fill_stops()
            self._edited()
