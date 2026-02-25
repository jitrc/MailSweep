"""AiWorker — background QObject for LLM chat interactions."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from mailsweep.ai.providers import LLMError, create_provider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an email organization assistant for MailSweep. You analyze IMAP mailbox \
structure, identify misfilings, dead folders, and cross-folder overlaps.

The user's mailbox data is provided below. Use it to answer questions about their \
email organization and suggest improvements.

When you suggest moving emails between folders, output structured MOVE lines:
```
MOVE: uid=12345, from="INBOX", to="IMP/Banks", reason="Axis Bank alert"
```

Rules for MOVE suggestions:
- Only suggest moves when the user asks for reorganization suggestions
- Each MOVE line must have uid, from, to, and reason fields
- The "from" and "to" must be exact IMAP folder names from the data
- Give a clear, short reason for each move

{context}
"""


class AiWorker(QObject):
    """Runs LLM chat in a background thread.

    Usage (moveToThread pattern — matches QtScanWorker):
        worker = AiWorker(message, history, context, provider, url, key, model)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        ...
        thread.start()
    """

    response_ready = pyqtSignal(str)    # AI response text
    error = pyqtSignal(str)             # error message
    thinking = pyqtSignal()             # started processing
    finished = pyqtSignal()

    def __init__(
        self,
        user_message: str,
        history: list[dict],
        context: str,
        provider_type: str,
        base_url: str,
        api_key: str,
        model: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._user_message = user_message
        self._history = list(history)
        self._context = context
        self._provider_type = provider_type
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    @pyqtSlot()
    def run(self) -> None:
        """Send user_message (with history and DB context) to the LLM."""
        self.thinking.emit()
        try:
            provider = create_provider(
                self._provider_type, self._base_url,
                self._api_key, self._model,
            )
        except LLMError as exc:
            self.error.emit(str(exc))
            self.finished.emit()
            return

        system = SYSTEM_PROMPT.format(context=self._context)
        messages = self._history + [
            {"role": "user", "content": self._user_message}
        ]

        try:
            reply = provider.chat(messages, system=system)
        except LLMError as exc:
            self.error.emit(str(exc))
            self.finished.emit()
            return
        except Exception as exc:
            self.error.emit(f"Unexpected error: {exc}")
            self.finished.emit()
            return

        self.response_ready.emit(reply)
        self.finished.emit()
