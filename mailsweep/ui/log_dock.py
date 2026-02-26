"""Log viewer dock widget — live-tailing app log with color by level."""
from __future__ import annotations

import logging
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDockWidget,
    QPlainTextEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)


_LEVEL_COLORS = {
    logging.DEBUG: QColor(140, 140, 140),
    logging.INFO: QColor(212, 212, 212),
    logging.WARNING: QColor(255, 200, 50),
    logging.ERROR: QColor(255, 80, 80),
    logging.CRITICAL: QColor(255, 0, 0),
}


class _SignalEmitter(QObject):
    log_record = pyqtSignal(int, str)  # level, message


class QtLogHandler(logging.Handler):
    """logging.Handler that emits a Qt signal for each log record."""

    def __init__(self) -> None:
        super().__init__()
        self._emitter = _SignalEmitter()
        self.log_record = self._emitter.log_record

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._emitter.log_record.emit(record.levelno, msg)
        except Exception:
            self.handleError(record)


class LogDockWidget(QDockWidget):
    def __init__(self, parent=None) -> None:
        super().__init__("Log", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._build_ui()
        self._install_handler()

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._clear)
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(5000)
        self._text.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; }"
        )
        font = self._text.font()
        font.setFamily("monospace")
        font.setPointSize(9)
        self._text.setFont(font)
        layout.addWidget(self._text)

        self.setWidget(container)

    def _install_handler(self) -> None:
        self._handler = QtLogHandler()
        formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        self._handler.setFormatter(formatter)
        self._handler.log_record.connect(self._append_log)
        logging.getLogger().addHandler(self._handler)
        self.destroyed.connect(self._remove_handler)

    def _remove_handler(self) -> None:
        logging.getLogger().removeHandler(self._handler)

    def _append_log(self, level: int, message: str) -> None:
        color = _LEVEL_COLORS.get(level, QColor(220, 220, 220))
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(message + "\n", fmt)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def _clear(self) -> None:
        self._text.clear()
