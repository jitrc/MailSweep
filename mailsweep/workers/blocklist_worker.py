"""BlocklistSyncWorker — fetches the community blocklist from a URL and saves to a local file."""
from __future__ import annotations
import urllib.request
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal


class BlocklistSyncWorker(QObject):
    finished = pyqtSignal(int, str)  # line_count, error_msg (empty = success)

    def __init__(self, url: str, dest_path: Path, parent=None):
        super().__init__(parent)
        self._url = url
        self._dest_path = dest_path

    def run(self) -> None:
        try:
            with urllib.request.urlopen(self._url, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            self.finished.emit(0, f"Failed to fetch blocklist: {exc}")
            return

        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        try:
            self._dest_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            self.finished.emit(0, f"Failed to save community blocklist: {exc}")
            return

        self.finished.emit(len(lines), "")
