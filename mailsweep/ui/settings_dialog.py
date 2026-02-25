"""Settings dialog — scan, UI, and AI settings."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import mailsweep.config as cfg
from mailsweep.ai.providers import PROVIDER_PRESETS


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── General group ────────────────────────────────────────────────────
        general_group = QGroupBox("General")
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

        self._unlabelled_mode = QComboBox()
        self._unlabelled_mode.addItem("No thread matching", "no_thread")
        self._unlabelled_mode.addItem("In-Reply-To chain", "in_reply_to")
        self._unlabelled_mode.addItem("Gmail Thread ID", "gmail_thread")
        form.addRow("Unlabelled detection:", self._unlabelled_mode)

        general_group.setLayout(form)
        layout.addWidget(general_group)

        # ── AI group ─────────────────────────────────────────────────────────
        ai_group = QGroupBox("AI Assistant")
        ai_form = QFormLayout()

        self._ai_provider = QComboBox()
        self._ai_provider.addItems(["ollama", "openai", "anthropic", "custom"])
        self._ai_provider.currentTextChanged.connect(self._on_ai_provider_changed)
        ai_form.addRow("Provider:", self._ai_provider)

        self._ai_base_url = QLineEdit()
        self._ai_base_url.setPlaceholderText("http://localhost:11434/v1")
        ai_form.addRow("Base URL:", self._ai_base_url)

        self._ai_api_key = QLineEdit()
        self._ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ai_api_key.setPlaceholderText("(not needed for Ollama)")
        ai_form.addRow("API Key:", self._ai_api_key)

        self._ai_model = QLineEdit()
        self._ai_model.setPlaceholderText("e.g. llama3.2")
        ai_form.addRow("Model:", self._ai_model)

        ai_group.setLayout(ai_form)
        layout.addWidget(ai_group)

        # ── Buttons ──────────────────────────────────────────────────────────
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

        mode_idx = self._unlabelled_mode.findData(cfg.UNLABELLED_MODE)
        if mode_idx >= 0:
            self._unlabelled_mode.setCurrentIndex(mode_idx)

        idx = self._ai_provider.findText(cfg.AI_PROVIDER)
        if idx >= 0:
            self._ai_provider.setCurrentIndex(idx)
        self._ai_base_url.setText(cfg.AI_BASE_URL)
        self._ai_api_key.setText(cfg.AI_API_KEY)
        self._ai_model.setText(cfg.AI_MODEL)

    def _on_ai_provider_changed(self, provider: str) -> None:
        preset = PROVIDER_PRESETS.get(provider, {})
        if preset.get("base_url"):
            self._ai_base_url.setText(preset["base_url"])
        if preset.get("model"):
            self._ai_model.setText(preset["model"])

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

        cfg.UNLABELLED_MODE = self._unlabelled_mode.currentData()

        cfg.AI_PROVIDER = self._ai_provider.currentText()
        cfg.AI_BASE_URL = self._ai_base_url.text().strip()
        cfg.AI_API_KEY = self._ai_api_key.text().strip()
        cfg.AI_MODEL = self._ai_model.text().strip()

        cfg.save_settings()
        self.accept()
