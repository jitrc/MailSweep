"""BackupWorker — FETCH RFC822 → save .eml → DELETE → EXPUNGE."""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import connect
from mailsweep.models.account import Account
from mailsweep.models.message import Message

logger = logging.getLogger(__name__)


class BackupWorker(QObject):
    """
    For each selected message:
      1. FETCH full RFC822 bytes
      2. Save to backup_dir/<folder>/<uid>_<subject_slug>.eml
      3. STORE uid +FLAGS \\Deleted
      4. EXPUNGE
    """

    progress = pyqtSignal(int, int, str)  # done, total, status_msg
    message_done = pyqtSignal(object, str)  # Message, saved_path
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        account: Account,
        messages: list[Message],
        backup_dir: Path,
        folder_id_to_name: dict[int, str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._messages = messages
        self._backup_dir = backup_dir
        self._folder_id_to_name = folder_id_to_name
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            client = connect(self._account)
        except Exception as exc:
            self.error.emit(f"Connection failed: {exc}")
            self.finished.emit()
            return

        total = len(self._messages)
        done = 0

        from collections import defaultdict
        by_folder: dict[int, list[Message]] = defaultdict(list)
        for msg in self._messages:
            by_folder[msg.folder_id].append(msg)

        try:
            for folder_id, folder_msgs in by_folder.items():
                if self._cancel_requested:
                    break

                folder_name = self._folder_id_to_name.get(folder_id, str(folder_id))
                folder_safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in folder_name)

                try:
                    client.select_folder(folder_name)
                except Exception as exc:
                    self.error.emit(f"Cannot select {folder_name}: {exc}")
                    continue

                for msg in folder_msgs:
                    if self._cancel_requested:
                        break

                    self.progress.emit(done, total, f"Backing up {msg.subject[:40]}…")
                    try:
                        fetch_data = client.fetch([msg.uid], [b"RFC822"])
                        if msg.uid not in fetch_data:
                            logger.warning("UID %d not found", msg.uid)
                            done += 1
                            continue

                        raw = fetch_data[msg.uid][b"RFC822"]

                        # Build filename
                        subject_slug = _slug(msg.subject or "no_subject")[:60]
                        filename = f"{msg.uid}_{subject_slug}.eml"
                        dest_dir = self._backup_dir / folder_safe
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dest = dest_dir / filename
                        dest.write_bytes(raw)

                        # Mark deleted + expunge
                        client.set_flags([msg.uid], [b"\\Deleted"])
                        try:
                            client.uid_expunge([msg.uid])
                        except Exception:
                            client.expunge()

                        self.message_done.emit(msg, str(dest))
                        done += 1
                        self.progress.emit(done, total, f"Backed up {done}/{total}")

                    except Exception as exc:
                        logger.error("Backup failed for UID %d: %s", msg.uid, exc)
                        self.error.emit(f"Failed to backup UID {msg.uid}: {exc}")
                        done += 1

        finally:
            try:
                client.logout()
            except Exception:
                pass
            self.finished.emit()


def _slug(text: str) -> str:
    """Convert text to a safe filesystem slug."""
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in text).strip()
