"""DeleteWorker — COPY to Trash → DELETE → EXPUNGE on a background thread."""
from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import connect, find_trash_folder
from mailsweep.models.account import Account
from mailsweep.models.message import Message

logger = logging.getLogger(__name__)

# Yahoo Mail rate-limits UID COPY — use small chunks with a delay between them.
# Flag+expunge are lighter and can be sent in one call for all UIDs.
_COPY_BATCH_SIZE = 15
_COPY_BATCH_DELAY = 1.0   # seconds between COPY chunks
_COPY_RETRY_DELAY = 5.0   # seconds to wait before retrying after a rate-limit error
_COPY_MAX_RETRIES = 3


class DeleteWorker(QObject):
    """
    Per folder:
      1. COPY UIDs to Trash in batches of _COPY_BATCH_SIZE (avoids server rate limits)
      2. STORE all UIDs +FLAGS \\Deleted in one call
      3. UID EXPUNGE all UIDs in one call (falls back to EXPUNGE if UIDPLUS unavailable)
    """

    progress = pyqtSignal(int, int, str)  # done, total, status_msg
    message_done = pyqtSignal(object, str)  # Message, status
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        account: Account,
        messages: list[Message],
        folder_id_to_name: dict[int, str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._messages = messages
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

        trash_folder = find_trash_folder(self._folder_id_to_name)

        try:
            for folder_id, folder_msgs in by_folder.items():
                if self._cancel_requested:
                    break

                folder_name = self._folder_id_to_name.get(folder_id, str(folder_id))
                try:
                    client.select_folder(folder_name, readonly=False)
                except Exception as exc:
                    err_lower = str(exc).lower()
                    if "does not exist" in err_lower or "trycreate" in err_lower:
                        # Folder is gone from server — prune from local cache
                        logger.warning("Folder %s no longer exists, pruning %d messages", folder_name, len(folder_msgs))
                        for msg in folder_msgs:
                            self.message_done.emit(msg, "deleted")
                    else:
                        self.error.emit(f"Cannot select {folder_name}: {exc}")
                        for msg in folder_msgs:
                            self.message_done.emit(msg, "error")
                    done += len(folder_msgs)
                    continue

                uids = [msg.uid for msg in folder_msgs]
                n = len(uids)
                self.progress.emit(done, total, f"Deleting {n} messages from {folder_name}…")

                try:
                    # COPY to Trash in small chunks with delay to avoid rate limits
                    if trash_folder and folder_name != trash_folder:
                        for i in range(0, n, _COPY_BATCH_SIZE):
                            if self._cancel_requested:
                                break
                            chunk = uids[i:i + _COPY_BATCH_SIZE]
                            for attempt in range(_COPY_MAX_RETRIES):
                                try:
                                    client.copy(chunk, trash_folder)
                                    break
                                except Exception as exc:
                                    if "rate limit" in str(exc).lower() and attempt < _COPY_MAX_RETRIES - 1:
                                        logger.warning("COPY rate limit hit, retrying in %.0fs…", _COPY_RETRY_DELAY)
                                        self.progress.emit(done, total, f"Rate limited — waiting {int(_COPY_RETRY_DELAY)}s…")
                                        time.sleep(_COPY_RETRY_DELAY)
                                    else:
                                        raise
                            copied = min(i + _COPY_BATCH_SIZE, n)
                            sender = folder_msgs[i].from_addr[:50]
                            self.progress.emit(done, total, f"{copied}/{n} to Trash — {sender}…")
                            logger.info("Copied UIDs %d-%d from %s to %s", i, copied, folder_name, trash_folder)
                            if i + _COPY_BATCH_SIZE < n:
                                time.sleep(_COPY_BATCH_DELAY)

                    if self._cancel_requested:
                        done += n
                        continue

                    # Flag and expunge all at once — these are cheap operations
                    client.set_flags(uids, [b"\\Deleted"])
                    try:
                        client.uid_expunge(uids)
                    except Exception:
                        logger.warning("UID EXPUNGE unavailable for %s, falling back to EXPUNGE", folder_name)
                        client.expunge()

                    for msg in folder_msgs:
                        self.message_done.emit(msg, "deleted")
                    done += n
                    self.progress.emit(done, total, f"Deleted {done}/{total}")

                except Exception as exc:
                    logger.error("Batch delete failed for %s: %s", folder_name, exc)
                    self.error.emit(f"Failed to delete messages in {folder_name}: {exc}")
                    done += n

        finally:
            try:
                client.logout()
            except Exception:
                pass
            self.finished.emit()
