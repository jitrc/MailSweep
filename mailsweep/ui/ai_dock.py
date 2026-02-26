"""AI Assistant dock widget — chat interface for LLM-powered mailbox analysis."""
from __future__ import annotations

import logging
import re

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
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

from mailsweep.ai.providers import PROVIDER_MODELS, PROVIDER_PRESETS, fetch_model_list

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
        self._provider_combo.addItems(["ollama", "lm-studio", "openai", "anthropic", "custom"])
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self._provider_combo)

        provider_row.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setMinimumWidth(250)
        provider_row.addWidget(self._model_combo)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Fetch available models from server")
        self._refresh_btn.setMaximumWidth(60)
        self._refresh_btn.clicked.connect(self._on_refresh_models)
        provider_row.addWidget(self._refresh_btn)
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

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setToolTip("Clear chat history")
        self._clear_btn.clicked.connect(self._on_clear)
        input_row.addWidget(self._clear_btn)
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
        self._populate_model_combo(cfg.AI_PROVIDER)
        self._model_combo.setCurrentText(cfg.AI_MODEL)
        if cfg.AI_API_KEY:
            self._key_edit.setText(cfg.AI_API_KEY)
        self._update_key_visibility()

    def _on_provider_changed(self, provider: str) -> None:
        preset = PROVIDER_PRESETS.get(provider, {})
        if preset.get("base_url"):
            self._url_edit.setText(preset["base_url"])
        self._populate_model_combo(provider)
        if preset.get("model"):
            self._model_combo.setCurrentText(preset["model"])
        self._update_key_visibility()

    def _populate_model_combo(self, provider: str) -> None:
        self._model_combo.clear()
        models = PROVIDER_MODELS.get(provider, [])
        if models:
            self._model_combo.addItems(models)

    def _update_key_visibility(self) -> None:
        hide = self._provider_combo.currentText() in ("ollama", "lm-studio")
        self._key_label.setVisible(not hide)
        self._key_edit.setVisible(not hide)

    def _on_refresh_models(self) -> None:
        base_url = self._url_edit.text().strip()
        api_key = self._key_edit.text().strip()
        if not base_url:
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("…")

        class _Fetcher(QObject):
            done = pyqtSignal(list)
            def __init__(self, url, key):
                super().__init__()
                self._url = url
                self._key = key
            def run(self):
                self.done.emit(fetch_model_list(self._url, self._key))

        thread = QThread(self)
        worker = _Fetcher(base_url, api_key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(lambda models: self._on_models_fetched(models))
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._refresh_thread = thread
        self._refresh_worker = worker
        thread.start()

    def _on_models_fetched(self, models: list[str]) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Refresh")
        if not models:
            return
        current = self._model_combo.currentText()
        existing = {self._model_combo.itemText(i) for i in range(self._model_combo.count())}
        for m in models:
            if m not in existing:
                self._model_combo.addItem(m)
        self._model_combo.setCurrentText(current)

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
        model = self._model_combo.currentText().strip()

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
        # Save cursor position so we can reliably remove "Thinking…" later
        self._thinking_cursor_pos = self._chat_browser.document().characterCount()
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
        # Remove the failed user message from history so context doesn't grow
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        self._append_chat("system", f"Error: {msg}")

    def _on_thread_done(self) -> None:
        self._ai_thread = None
        self._ai_worker = None
        self._send_btn.setEnabled(True)

    def _on_clear(self) -> None:
        """Reset chat history and display."""
        self._history.clear()
        self._last_response = ""
        self._chat_browser.clear()
        self._apply_btn.setEnabled(False)

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
        """Remove the 'Thinking…' message added by _on_thinking()."""
        pos = getattr(self, "_thinking_cursor_pos", None)
        if pos is None:
            return
        cursor = self._chat_browser.textCursor()
        # Select from saved position to end and remove
        cursor.setPosition(max(pos - 1, 0))
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._thinking_cursor_pos = None


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
