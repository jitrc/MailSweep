"""Treemap widget — squarify layout painted with QPainter. Click to filter."""
from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from mailsweep.utils.size_fmt import human_size

try:
    import squarify
    _HAS_SQUARIFY = True
except ImportError:
    _HAS_SQUARIFY = False


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
    key: str          # unique identifier (folder_id, email addr, or uid)
    label: str        # display name
    sublabel: str     # second line (e.g. "42 msgs" or folder name)
    size_bytes: int


VIEW_FOLDERS = 0
VIEW_SENDERS = 1
VIEW_MESSAGES = 2


class _TreemapCanvas(QWidget):
    """Internal paint surface for the treemap tiles."""
    item_clicked = pyqtSignal(str)  # key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[TreemapItem] = []
        self._rects: list[tuple[QRectF, TreemapItem]] = []
        self._hovered_key: str | None = None
        self.setMinimumHeight(100)
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "No data — scan a mailbox first")
            return

        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        fm = QFontMetrics(font)

        for i, (rect, item) in enumerate(self._rects):
            color = _PALETTE[i % len(_PALETTE)]
            if item.key == self._hovered_key:
                color = color.lighter(130)

            painter.fillRect(rect, color)
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
            painter.drawRect(rect)

            iw, ih = int(rect.width()), int(rect.height())
            if iw > 40 and ih > 20:
                text_rect = rect.adjusted(4, 4, -4, -4)
                size_str = human_size(item.size_bytes)

                lh = fm.height() + 2  # line height: font height + 2px spacing
                tx = text_rect.x()
                tw = text_rect.width()
                max_text_w = iw - 8

                painter.setPen(QColor(255, 255, 255))
                if ih > 48 and item.sublabel:
                    # Three lines stacked from top: label, sublabel, size
                    ty = text_rect.y()
                    painter.drawText(QRectF(tx, ty, tw, lh),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     fm.elidedText(item.label, Qt.TextElideMode.ElideRight, max_text_w))
                    ty += lh
                    painter.setPen(QColor(255, 255, 255, 180))
                    painter.drawText(QRectF(tx, ty, tw, lh),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     fm.elidedText(item.sublabel, Qt.TextElideMode.ElideRight, max_text_w))
                    ty += lh
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(QRectF(tx, ty, tw, lh),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     size_str)
                elif ih > 36:
                    # Two lines: label + size
                    ty = text_rect.y()
                    painter.drawText(QRectF(tx, ty, tw, lh),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     fm.elidedText(item.label, Qt.TextElideMode.ElideRight, max_text_w))
                    ty += lh
                    painter.drawText(QRectF(tx, ty, tw, lh),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     size_str)
                else:
                    combined = f"{item.label} ({size_str})"
                    painter.drawText(text_rect,
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     fm.elidedText(combined, Qt.TextElideMode.ElideRight, max_text_w))

        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        hovered = None
        for rect, item in self._rects:
            if rect.contains(pos):
                hovered = item.key
                break
        if hovered != self._hovered_key:
            self._hovered_key = hovered
            self.update()
            if hovered is not None:
                found = next((it for _, it in self._rects if it.key == hovered), None)
                if found:
                    tip = f"{found.label}\n{found.sublabel}\n{human_size(found.size_bytes)}" if found.sublabel else f"{found.label}\n{human_size(found.size_bytes)}"
                    self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for rect, item in self._rects:
                if rect.contains(pos):
                    self.item_clicked.emit(item.key)
                    break
        super().mousePressEvent(event)


class TreemapWidget(QWidget):
    """
    Composite widget: view-mode selector + treemap canvas.
    Emits typed signals depending on view mode.
    """
    folder_clicked = pyqtSignal(int)     # folder_id
    folder_key_clicked = pyqtSignal(str) # raw key (folder_id, "path:...", or "msg:...")
    sender_clicked = pyqtSignal(str)     # from_addr
    message_clicked = pyqtSignal(int)    # message uid
    view_mode_changed = pyqtSignal(int)  # VIEW_FOLDERS / VIEW_SENDERS / VIEW_MESSAGES

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_mode = VIEW_FOLDERS
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.addWidget(QLabel("View:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Folders", VIEW_FOLDERS)
        self._mode_combo.addItem("Senders", VIEW_SENDERS)
        self._mode_combo.addItem("Messages", VIEW_MESSAGES)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._mode_combo.setFixedWidth(120)
        header.addWidget(self._mode_combo)
        header.addStretch()
        layout.addLayout(header)

        self._canvas = _TreemapCanvas()
        self._canvas.item_clicked.connect(self._on_item_clicked)
        layout.addWidget(self._canvas, stretch=1)

    def _on_mode_changed(self, idx: int) -> None:
        self._view_mode = self._mode_combo.itemData(idx)
        self.view_mode_changed.emit(self._view_mode)

    def _on_item_clicked(self, key: str) -> None:
        if self._view_mode == VIEW_FOLDERS:
            self.folder_key_clicked.emit(key)
            try:
                self.folder_clicked.emit(int(key))
            except ValueError:
                pass
        elif self._view_mode == VIEW_SENDERS:
            self.sender_clicked.emit(key)
        elif self._view_mode == VIEW_MESSAGES:
            try:
                self.message_clicked.emit(int(key))
            except ValueError:
                pass

    @property
    def view_mode(self) -> int:
        return self._view_mode

    def set_data(self, items: list[TreemapItem]) -> None:
        self._canvas.set_data(items)

    def setMinimumHeight(self, h: int) -> None:
        super().setMinimumHeight(h)
