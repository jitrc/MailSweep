"""Settings dialog — scan chunk size, size thresholds, default save dir."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import mailsweep.config as cfg


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._chunk_size = QSpinBox()
        self._chunk_size.setRange(50, 2000)
        self._chunk_size.setSingleStep(50)
        form.addRow("Scan batch size:", self._chunk_size)

        self._max_rows = QSpinBox()
        self._max_rows.setRange(100, 50000)
        self._max_rows.setSingleStep(1000)
        form.addRow("Max table rows:", self._max_rows)

        save_row = QHBoxLayout()
        self._save_dir_edit = QLineEdit()
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        save_row.addWidget(self._save_dir_edit)
        save_row.addWidget(browse_btn)
        form.addRow("Attachment save dir:", save_row)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self) -> None:
        self._chunk_size.setValue(cfg.SCAN_BATCH_SIZE)
        self._max_rows.setValue(cfg.MESSAGE_TABLE_MAX_ROWS)
        self._save_dir_edit.setText(str(cfg.DEFAULT_SAVE_DIR))

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", str(cfg.DEFAULT_SAVE_DIR)
        )
        if path:
            self._save_dir_edit.setText(path)

    def _on_accept(self) -> None:
        cfg.SCAN_BATCH_SIZE = self._chunk_size.value()
        cfg.MESSAGE_TABLE_MAX_ROWS = self._max_rows.value()
        save_path = Path(self._save_dir_edit.text().strip())
        save_path.mkdir(parents=True, exist_ok=True)
        cfg.DEFAULT_SAVE_DIR = save_path
        cfg.save_settings()
        self.accept()
