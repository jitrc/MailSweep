"""DetachWorker — FETCH → strip attachments → APPEND → DELETE → EXPUNGE."""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import connect
from mailsweep.models.account import Account
from mailsweep.models.message import Message
from mailsweep.utils.mime_utils import strip_attachments

logger = logging.getLogger(__name__)


class DetachWorker(QObject):
    """
    For each selected message:
      1. FETCH full RFC822 bytes + FLAGS + INTERNALDATE
      2. Strip attachments, save to save_dir
      3. APPEND cleaned bytes to same folder (preserving flags and date)
      4. STORE uid +FLAGS \\Deleted
      5. EXPUNGE
    """

    progress = pyqtSignal(int, int, str)  # done, total, status_msg
    message_done = pyqtSignal(object, list)  # Message, saved_filenames
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        account: Account,
        messages: list[Message],
        save_dir: Path,
        folder_id_to_name: dict[int, str],
        detach_from_server: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._messages = messages
        self._save_dir = save_dir
        self._folder_id_to_name = folder_id_to_name
        self._detach_from_server = detach_from_server
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

        # Group messages by folder to avoid constant folder switching
        from collections import defaultdict
        by_folder: dict[int, list[Message]] = defaultdict(list)
        for msg in self._messages:
            by_folder[msg.folder_id].append(msg)

        done = 0
        try:
            for folder_id, folder_msgs in by_folder.items():
                if self._cancel_requested:
                    break

                folder_name = self._folder_id_to_name.get(folder_id, str(folder_id))
                try:
                    client.select_folder(folder_name, readonly=False)
                except Exception as exc:
                    self.error.emit(f"Cannot select {folder_name}: {exc}")
                    continue

                for msg in folder_msgs:
                    if self._cancel_requested:
                        break

                    self.progress.emit(done, total, f"Detaching attachments from {msg.subject[:40]}…")
                    try:
                        # Fetch full message
                        fetch_data = client.fetch([msg.uid], [b"RFC822", b"FLAGS", b"INTERNALDATE"])
                        if msg.uid not in fetch_data:
                            logger.warning("UID %d not found in folder %s", msg.uid, folder_name)
                            done += 1
                            continue

                        raw = fetch_data[msg.uid][b"RFC822"]
                        orig_flags = fetch_data[msg.uid].get(b"FLAGS", [])
                        orig_date = fetch_data[msg.uid].get(b"INTERNALDATE")

                        # Strip attachments — save to <label>/<subject_slug>/
                        folder_safe = _slug(folder_name)
                        subject_slug = _slug(msg.subject or "no_subject")[:60]
                        save_subdir = self._save_dir / folder_safe / f"{msg.uid}_{subject_slug}"
                        cleaned_bytes, saved_names = strip_attachments(raw, save_subdir, msg.uid)

                        if not saved_names:
                            logger.info("No attachments found in UID %d", msg.uid)
                            done += 1
                            self.progress.emit(done, total, f"No attachments in UID {msg.uid}")
                            continue

                        if self._detach_from_server:
                            # Replace message on server with stripped version
                            append_flags = [f for f in orig_flags if f not in (b"\\Recent",)]
                            logger.info(
                                "APPEND stripped message to %s (orig UID %d, %d→%d bytes)",
                                folder_name, msg.uid, len(raw), len(cleaned_bytes),
                            )
                            append_result = client.append(
                                folder_name, cleaned_bytes, append_flags, orig_date,
                            )
                            logger.info("APPEND result: %s", append_result)
                            client.set_flags([msg.uid], [b"\\Deleted"])
                            logger.info("Marked UID %d as \\Deleted", msg.uid)
                            try:
                                client.uid_expunge([msg.uid])
                                logger.info("UID EXPUNGE %d done", msg.uid)
                            except Exception:
                                client.expunge()
                                logger.info("EXPUNGE (non-UID) done for folder %s", folder_name)

                        self.message_done.emit(msg, saved_names)

                    except Exception as exc:
                        logger.error("Detach failed for UID %d: %s", msg.uid, exc)
                        self.error.emit(f"Failed to detach UID {msg.uid}: {exc}")

                    done += 1
                    self.progress.emit(done, total, f"Detached {done}/{total}")

        finally:
            try:
                client.logout()
            except Exception:
                pass
            self.finished.emit()


def _slug(text: str) -> str:
    """Convert text to a safe filesystem slug."""
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in text).strip()
