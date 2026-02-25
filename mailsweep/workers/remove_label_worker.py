"""RemoveLabelWorker — remove messages from specific IMAP folders without Trash copy.

Used after Find Duplicate Labels: the message exists in other folders,
so we just expunge it from the selected folder (no Gmail-safe Trash copy needed).
"""
from __future__ import annotations

import logging
from collections import defaultdict

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import connect
from mailsweep.models.account import Account
from mailsweep.models.message import Message

logger = logging.getLogger(__name__)


class RemoveLabelWorker(QObject):
    """
    For each selected message:
      1. SELECT the folder
      2. STORE uid +FLAGS \\Deleted
      3. UID EXPUNGE
    No Trash copy — the message still exists in other folders.
    """

    progress = pyqtSignal(int, int, str)   # done, total, status_msg
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

        by_folder: dict[int, list[Message]] = defaultdict(list)
        for msg in self._messages:
            by_folder[msg.folder_id].append(msg)

        try:
            for folder_id, folder_msgs in by_folder.items():
                if self._cancel_requested:
                    break

                folder_name = self._folder_id_to_name.get(folder_id, str(folder_id))
                try:
                    client.select_folder(folder_name, readonly=False)
                except Exception as exc:
                    self.error.emit(f"Cannot select {folder_name}: {exc}")
                    done += len(folder_msgs)
                    continue

                for msg in folder_msgs:
                    if self._cancel_requested:
                        break

                    self.progress.emit(done, total, f"Removing from {folder_name}…")
                    try:
                        client.set_flags([msg.uid], [b"\\Deleted"])
                        try:
                            client.uid_expunge([msg.uid])
                        except Exception:
                            logger.warning(
                                "UID EXPUNGE not supported for UID %d in %s, "
                                "message flagged but not expunged",
                                msg.uid, folder_name,
                            )

                        self.message_done.emit(msg, "label_removed")
                    except Exception as exc:
                        logger.error("Remove label failed for UID %d: %s", msg.uid, exc)
                        self.error.emit(f"Failed to remove UID {msg.uid} from {folder_name}: {exc}")

                    done += 1
                    self.progress.emit(done, total, f"Removed {done}/{total}")

        finally:
            try:
                client.logout()
            except Exception:
                pass
            self.finished.emit()
