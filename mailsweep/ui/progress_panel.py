"""Progress panel — status label + progress bar + cancel button."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)


class ProgressPanel(QWidget):
    cancel_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.set_idle()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._status_label = QLabel("Ready")
        self._status_label.setMinimumWidth(300)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setMinimumWidth(200)
        self._progress_bar.setMaximumWidth(300)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setFixedWidth(70)
        self._cancel_button.clicked.connect(self.cancel_clicked)

        layout.addWidget(self._status_label, stretch=1)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._cancel_button)

    def set_idle(self) -> None:
        self._status_label.setText("Ready")
        self._progress_bar.setValue(0)
        self._progress_bar.setRange(0, 100)
        self._cancel_button.setEnabled(False)

    def set_running(self, message: str) -> None:
        self._status_label.setText(message)
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._cancel_button.setEnabled(True)

    def set_progress(self, done: int, total: int, message: str = "") -> None:
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(done)
        if message:
            self._status_label.setText(message)
        self._cancel_button.setEnabled(True)

    def set_error(self, message: str) -> None:
        self._status_label.setText(f"Error: {message}")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._cancel_button.setEnabled(False)

    def set_done(self, message: str = "Done") -> None:
        self._status_label.setText(message)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._cancel_button.setEnabled(False)
