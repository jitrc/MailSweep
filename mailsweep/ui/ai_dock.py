"""AI Assistant dock widget — chat interface for LLM-powered mailbox analysis."""
from __future__ import annotations

import logging
import re

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from typing import NamedTuple

from mailsweep.ai.providers import PROVIDER_PRESETS

logger = logging.getLogger(__name__)


class AiMoveOp(NamedTuple):
    """Unresolved AI move suggestion (sender-based, not UID-based)."""
    sender: str
    src_folder: str
    dst_folder: str
    reason: str


# Regex to parse MOVE: lines from AI responses
_MOVE_RE = re.compile(
    r'MOVE:\s*sender="([^"]+)"\s*,\s*from="([^"]+)"\s*,\s*to="([^"]+)"\s*,\s*reason="([^"]*)"',
    re.IGNORECASE,
)


class AiDockWidget(QDockWidget):
    """Dockable AI chat panel for mailbox analysis."""

    # Emitted when user clicks "Apply Suggestions" with parsed AI move ops
    apply_moves = pyqtSignal(list)  # list[AiMoveOp]
    # Request context from main window
    context_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__("AI Assistant", parent)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._history: list[dict] = []
        self._context: str = ""
        self._last_response: str = ""
        self._ai_thread: QThread | None = None
        self._ai_worker = None
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Provider / model row ─────────────────────────────────────────────
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provider:"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["ollama", "openai", "anthropic", "custom"])
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self._provider_combo)

        provider_row.addWidget(QLabel("Model:"))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("e.g. llama3.2")
        self._model_edit.setMinimumWidth(120)
        provider_row.addWidget(self._model_edit)
        layout.addLayout(provider_row)

        url_key_row = QHBoxLayout()
        url_key_row.addWidget(QLabel("URL:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://localhost:11434/v1")
        url_key_row.addWidget(self._url_edit)

        self._key_label = QLabel("Key:")
        url_key_row.addWidget(self._key_label)
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("(not needed for Ollama)")
        self._key_edit.setMinimumWidth(100)
        url_key_row.addWidget(self._key_edit)
        layout.addLayout(url_key_row)

        # ── Chat history ─────────────────────────────────────────────────────
        self._chat_browser = QTextBrowser()
        self._chat_browser.setOpenExternalLinks(False)
        self._chat_browser.setMinimumHeight(200)
        layout.addWidget(self._chat_browser, stretch=1)

        # ── Apply suggestions button ─────────────────────────────────────────
        self._apply_btn = QPushButton("Apply Suggestions (MOVE)")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        # ── Quick action buttons ─────────────────────────────────────────────
        quick_row = QHBoxLayout()
        for label, prompt in [
            ("Analyze folders", "Analyze my folder organization. Which folders are well-organized and which need cleanup?"),
            ("Find misfilings", "Find emails that appear to be misfiled based on sender patterns and folder naming."),
            ("Find duplicates", "Identify folders with significant sender overlap that could be consolidated."),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, p=prompt: self._send_message(p))
            quick_row.addWidget(btn)
        layout.addLayout(quick_row)

        # ── Input row ────────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText("Ask about your email organization…")
        self._input_edit.returnPressed.connect(self._on_send)
        input_row.addWidget(self._input_edit)

        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._send_btn)
        layout.addLayout(input_row)

        self.setWidget(container)

        # Apply initial provider preset
        self._load_from_config()

    def _load_from_config(self) -> None:
        """Load AI settings from config module."""
        import mailsweep.config as cfg
        idx = self._provider_combo.findText(cfg.AI_PROVIDER)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._url_edit.setText(cfg.AI_BASE_URL)
        self._model_edit.setText(cfg.AI_MODEL)
        if cfg.AI_API_KEY:
            self._key_edit.setText(cfg.AI_API_KEY)
        self._update_key_visibility()

    def _on_provider_changed(self, provider: str) -> None:
        preset = PROVIDER_PRESETS.get(provider, {})
        if preset.get("base_url"):
            self._url_edit.setText(preset["base_url"])
        if preset.get("model"):
            self._model_edit.setText(preset["model"])
        self._update_key_visibility()

    def _update_key_visibility(self) -> None:
        hide = self._provider_combo.currentText() == "ollama"
        self._key_label.setVisible(not hide)
        self._key_edit.setVisible(not hide)

    def set_context(self, context: str) -> None:
        """Set the DB context string (called by main_window)."""
        self._context = context

    def _on_send(self) -> None:
        text = self._input_edit.text().strip()
        if not text:
            return
        self._input_edit.clear()
        self._send_message(text)

    def _send_message(self, text: str) -> None:
        if self._ai_thread and self._ai_thread.isRunning():
            self._append_chat("system", "Please wait — still processing previous request…")
            return

        provider = self._provider_combo.currentText()
        base_url = self._url_edit.text().strip()
        api_key = self._key_edit.text().strip()
        model = self._model_edit.text().strip()

        if not model:
            self._append_chat("system", "Please set a model name first.")
            return

        # Request fresh context from main window
        self.context_requested.emit()

        self._append_chat("user", text)

        # Save current settings back to config
        self._save_to_config(provider, base_url, api_key, model)

        from mailsweep.workers.ai_worker import AiWorker

        worker = AiWorker(
            user_message=text,
            history=list(self._history),
            context=self._context,
            provider_type=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        # Connect signals — worker lives in thread, slots in main thread,
        # so AutoConnection correctly resolves to QueuedConnection.
        thread.started.connect(worker.run)
        worker.thinking.connect(self._on_thinking)
        worker.response_ready.connect(self._on_response)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_done)

        self._ai_worker = worker
        self._ai_thread = thread
        self._send_btn.setEnabled(False)
        thread.start()

    def _save_to_config(self, provider: str, base_url: str, api_key: str, model: str) -> None:
        import mailsweep.config as cfg
        cfg.AI_PROVIDER = provider
        cfg.AI_BASE_URL = base_url
        cfg.AI_API_KEY = api_key
        cfg.AI_MODEL = model
        cfg.save_settings()

    def _on_thinking(self) -> None:
        self._append_chat("system", "Thinking…")

    def _on_response(self, text: str) -> None:
        # Remove the "Thinking…" message
        self._remove_last_system()
        self._append_chat("assistant", text)
        self._history.append({"role": "assistant", "content": text})
        self._last_response = text
        # Enable apply button if MOVE lines found
        moves = _MOVE_RE.findall(text)
        self._apply_btn.setEnabled(bool(moves))

    def _on_error(self, msg: str) -> None:
        self._remove_last_system()
        self._append_chat("system", f"Error: {msg}")

    def _on_thread_done(self) -> None:
        self._ai_thread = None
        self._ai_worker = None
        self._send_btn.setEnabled(True)

    def _on_apply(self) -> None:
        moves = _MOVE_RE.findall(self._last_response)
        if not moves:
            return
        ops = [AiMoveOp(sender=m[0], src_folder=m[1], dst_folder=m[2], reason=m[3]) for m in moves]
        self.apply_moves.emit(ops)

    def _append_chat(self, role: str, text: str) -> None:
        if role == "user":
            self._history.append({"role": "user", "content": text})
            html = f'<p style="color: #1565c0;"><b>You:</b> {_escape(text)}</p>'
        elif role == "assistant":
            # Convert markdown-ish text to basic HTML
            html = f'<p style="color: #2e7d32;"><b>AI:</b><br>{_format_response(text)}</p>'
        else:
            html = f'<p style="color: #e65100;"><i>{_escape(text)}</i></p>'
        self._chat_browser.append(html)

    def _remove_last_system(self) -> None:
        """Remove the last 'Thinking…' system message from the display."""
        cursor = self._chat_browser.textCursor()
        doc = self._chat_browser.document()
        # Find and remove the last block if it was our thinking message
        block = doc.lastBlock()
        if block.isValid() and "Thinking" in block.text():
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.deletePreviousChar()  # remove trailing newline


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_response(text: str) -> str:
    """Basic markdown → HTML conversion for AI responses."""
    text = _escape(text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Code blocks
    text = re.sub(
        r"```(.*?)```",
        r'<pre style="background:#e8e8e8; padding:4px; color:#333;">\1</pre>',
        text,
        flags=re.DOTALL,
    )
    # Inline code
    text = re.sub(r"`([^`]+)`", r'<code style="background:#e8e8e8; color:#333;">\1</code>', text)
    # MOVE lines — highlight them
    text = re.sub(
        r"(MOVE:.*)",
        r'<span style="color: #bf360c; font-weight: bold;">\1</span>',
        text,
    )
    # Newlines
    text = text.replace("\n", "<br>")
    return text
