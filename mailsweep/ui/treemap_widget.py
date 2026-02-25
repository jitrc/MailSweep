"""Treemap widget — squarify layout painted with QPainter. Click to filter."""
from __future__ import annotations

import math
from typing import NamedTuple

from PyQt6.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from mailsweep.utils.size_fmt import human_size

try:
    import squarify
    _HAS_SQUARIFY = True
except ImportError:
    _HAS_SQUARIFY = False


# Palette for folder tiles
_PALETTE = [
    QColor(70, 130, 180),   # steel blue
    QColor(60, 179, 113),   # medium sea green
    QColor(210, 105, 30),   # chocolate
    QColor(147, 112, 219),  # medium purple
    QColor(220, 20, 60),    # crimson
    QColor(32, 178, 170),   # light sea green
    QColor(255, 165, 0),    # orange
    QColor(106, 90, 205),   # slate blue
    QColor(128, 128, 0),    # olive
    QColor(199, 21, 133),   # medium violet red
]


class TreemapItem(NamedTuple):
    folder_id: int
    folder_name: str
    size_bytes: int


class TreemapWidget(QWidget):
    """
    Draws a squarify treemap of folder sizes.
    Emits folder_clicked(folder_id) when user clicks a tile.
    """
    folder_clicked = pyqtSignal(int)  # folder_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[TreemapItem] = []
        self._rects: list[tuple[QRectF, TreemapItem]] = []
        self._hovered_id: int | None = None
        self.setMinimumHeight(120)
        self.setMouseTracking(True)

    def set_data(self, items: list[TreemapItem]) -> None:
        self._items = [i for i in items if i.size_bytes > 0]
        self._compute_rects()
        self.update()

    def _compute_rects(self) -> None:
        self._rects.clear()
        if not self._items or not _HAS_SQUARIFY:
            return

        items_sorted = sorted(self._items, key=lambda x: x.size_bytes, reverse=True)
        values = [i.size_bytes for i in items_sorted]
        total = sum(values)
        if total == 0:
            return

        w = max(self.width(), 1)
        h = max(self.height(), 1)

        normalized = squarify.normalize_sizes(values, w, h)
        rects = squarify.squarify(normalized, 0, 0, w, h)

        for item, r in zip(items_sorted, rects):
            self._rects.append((
                QRectF(r["x"], r["y"], r["dx"], r["dy"]),
                item,
            ))

    def resizeEvent(self, event) -> None:
        self._compute_rects()
        super().resizeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        bg = self.palette().window().color()
        painter.fillRect(self.rect(), bg)

        if not self._rects:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data — scan a mailbox first")
            return

        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        fm = QFontMetrics(font)

        for i, (rect, item) in enumerate(self._rects):
            color = _PALETTE[i % len(_PALETTE)]
            is_hovered = item.folder_id == self._hovered_id

            if is_hovered:
                color = color.lighter(130)

            painter.fillRect(rect, color)
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
            painter.drawRect(rect)

            # Draw label if tile is large enough
            iw, ih = int(rect.width()), int(rect.height())
            if iw > 40 and ih > 20:
                text_rect = rect.adjusted(4, 4, -4, -4)
                display_name = item.folder_name.split("/")[-1]
                size_str = human_size(item.size_bytes)

                painter.setPen(QColor(255, 255, 255))
                if ih > 36:
                    # Two lines: name + size
                    name_rect = QRectF(text_rect.x(), text_rect.y(),
                                       text_rect.width(), text_rect.height() / 2)
                    size_rect = QRectF(text_rect.x(), text_rect.y() + text_rect.height() / 2,
                                       text_rect.width(), text_rect.height() / 2)
                    painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     fm.elidedText(display_name, Qt.TextElideMode.ElideRight, iw - 8))
                    painter.drawText(size_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     size_str)
                else:
                    combined = f"{display_name} ({size_str})"
                    painter.drawText(text_rect,
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     fm.elidedText(combined, Qt.TextElideMode.ElideRight, iw - 8))

        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        hovered = None
        for rect, item in self._rects:
            if rect.contains(pos):
                hovered = item.folder_id
                break
        if hovered != self._hovered_id:
            self._hovered_id = hovered
            self.update()
            if hovered is not None:
                item_found = next((it for _, it in self._rects if it.folder_id == hovered), None)
                if item_found:
                    self.setToolTip(f"{item_found.folder_name}\n{human_size(item_found.size_bytes)}")
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for rect, item in self._rects:
                if rect.contains(pos):
                    self.folder_clicked.emit(item.folder_id)
                    break
        super().mousePressEvent(event)
