"""QObject wrapper around ScanWorker for use with QThread (moveToThread pattern)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import IMAPConnectionError, connect
from mailsweep.models.account import Account
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message
from mailsweep.workers.incremental_scan import get_new_deleted_uids
from mailsweep.workers.scan_worker import ScanWorker

logger = logging.getLogger(__name__)


class QtScanWorker(QObject):
    """
    Runs ScanWorker on a background thread.

    Usage (moveToThread pattern):
        worker = QtScanWorker(account, folders, folder_repo, msg_repo)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
    """

    # Signals
    folder_started = pyqtSignal(str)                   # folder_name
    message_batch_done = pyqtSignal(list, int, int)    # messages, done, total
    folder_done = pyqtSignal(object)                   # Folder (updated stats)
    all_done = pyqtSignal()
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        account: Account,
        folders: list[Folder],
        folder_repo,
        msg_repo,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._folders = folders
        self._folder_repo = folder_repo
        self._msg_repo = msg_repo
        self._cancel_requested = False
        self._current_worker: ScanWorker | None = None

    def cancel(self) -> None:
        self._cancel_requested = True
        if self._current_worker:
            self._current_worker.cancel()

    def run(self) -> None:
        try:
            client = connect(self._account)
        except IMAPConnectionError as exc:
            self.error.emit(str(exc))
            self.finished.emit()
            return

        try:
            for folder in self._folders:
                if self._cancel_requested:
                    break

                assert folder.id is not None
                self.folder_started.emit(folder.name)

                # UID validity check
                try:
                    status = client.select_folder(folder.name, readonly=True)
                    server_uidvalidity = int(status.get(b"UIDVALIDITY", 0))
                except Exception as exc:
                    logger.warning("Cannot select %s: %s", folder.name, exc)
                    continue

                cache_valid = (
                    folder.uid_validity != 0
                    and folder.uid_validity == server_uidvalidity
                )

                if not cache_valid:
                    if folder.uid_validity and folder.uid_validity != server_uidvalidity:
                        logger.info("UID validity changed for %s — full rescan", folder.name)
                    else:
                        logger.info("No cache for %s — full scan", folder.name)
                    self._folder_repo.invalidate(folder.id)
                    new_uids = None       # None → ScanWorker fetches all
                    deleted_uids: list[int] = []
                else:
                    # Incremental: only fetch UIDs the server has that we don't,
                    # and remove UIDs we have that the server deleted.
                    new_uids, deleted_uids = get_new_deleted_uids(
                        client, folder.id, self._msg_repo
                    )
                    if deleted_uids:
                        self._msg_repo.delete_uids(folder.id, deleted_uids)
                        logger.info("%s: removed %d deleted UIDs from cache",
                                    folder.name, len(deleted_uids))

                    if not new_uids:
                        logger.info("%s: cache up to date, skipping fetch", folder.name)
                        # Still emit folder_done so UI stays current
                        self._folder_repo.update_stats(folder.id)
                        updated = self._folder_repo.get_by_id(folder.id)
                        if updated:
                            self.folder_done.emit(updated)
                        continue

                    logger.info("%s: incremental — fetching %d new UIDs", folder.name, len(new_uids))

                def on_batch_emit(msgs: list[Message], _fid=folder.id) -> None:
                    self._msg_repo.upsert_batch(msgs)
                    self.message_batch_done.emit(msgs, 0, 0)

                def on_progress(done: int, total: int, _fname=folder.name) -> None:
                    self.message_batch_done.emit([], done, total)

                worker = ScanWorker(
                    client=client,
                    folder_id=folder.id,
                    folder_name=folder.name,
                    on_batch=on_batch_emit,
                    on_progress=on_progress,
                )
                self._current_worker = worker

                try:
                    worker.run(uids=new_uids)
                except Exception as exc:
                    logger.error("Scan error for %s: %s", folder.name, exc)
                    self.error.emit(f"Error scanning {folder.name}: {exc}")
                    continue

                # Update folder metadata
                folder.uid_validity = server_uidvalidity
                folder.last_scanned_at = datetime.now(timezone.utc)
                self._folder_repo.upsert(folder)
                self._folder_repo.update_stats(folder.id)

                updated = self._folder_repo.get_by_id(folder.id)
                if updated:
                    self.folder_done.emit(updated)

        finally:
            try:
                client.logout()
            except Exception:
                pass
            self._current_worker = None
            self.all_done.emit()
            self.finished.emit()
