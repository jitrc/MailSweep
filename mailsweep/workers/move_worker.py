"""MoveWorker — IMAP move operations (RFC 6851 with copy+delete fallback)."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import connect
from mailsweep.models.account import Account

logger = logging.getLogger(__name__)


class MoveOp(NamedTuple):
    uid: int
    src_folder: str
    dst_folder: str


class MoveWorker(QObject):
    """Move messages between IMAP folders in a background thread.

    Batches moves by source folder to minimize IMAP SELECT switches.
    Uses MOVE (RFC 6851) with copy+delete fallback.
    """

    progress = pyqtSignal(int, int, str)   # done, total, status
    finished = pyqtSignal(int)             # count moved
    error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self, account: Account, moves: list[MoveOp], conn=None, folder_repo=None, msg_repo=None) -> None:
        """Execute all move operations.

        conn, folder_repo, msg_repo: if provided, update the local DB cache
        after successful moves.
        """
        if not moves:
            self.finished.emit(0)
            return

        total = len(moves)
        done = 0

        try:
            client = connect(account)
        except Exception as exc:
            self.error.emit(f"Connection failed: {exc}")
            self.finished.emit(0)
            return

        # Group moves by source folder for efficient SELECT batching
        by_src: dict[str, list[MoveOp]] = defaultdict(list)
        for op in moves:
            by_src[op.src_folder].append(op)

        # Detect MOVE capability once
        try:
            caps = client.capabilities()
            has_move = b"MOVE" in caps
        except Exception:
            has_move = False

        try:
            for src_folder, ops in by_src.items():
                if self._cancel_requested:
                    break

                try:
                    client.select_folder(src_folder)
                except Exception as exc:
                    logger.error("Cannot select %s: %s", src_folder, exc)
                    self.error.emit(f"Cannot select folder {src_folder}: {exc}")
                    done += len(ops)
                    continue

                # Group UIDs by destination
                by_dst: dict[str, list[int]] = defaultdict(list)
                for op in ops:
                    by_dst[op.dst_folder].append(op.uid)

                for dst_folder, uids in by_dst.items():
                    if self._cancel_requested:
                        break

                    self.progress.emit(done, total, f"Moving to {dst_folder}…")

                    try:
                        if has_move:
                            client.move(uids, dst_folder)
                        else:
                            # Fallback: COPY + DELETE + EXPUNGE
                            client.copy(uids, dst_folder)
                            client.delete_messages(uids)
                            client.expunge(uids)

                        # Update local DB cache
                        if conn and folder_repo and msg_repo:
                            _update_db_after_move(
                                conn, folder_repo, msg_repo,
                                uids, src_folder, dst_folder, account.id,
                            )

                        done += len(uids)
                        logger.info(
                            "Moved %d message(s) from %s to %s",
                            len(uids), src_folder, dst_folder,
                        )

                    except Exception as exc:
                        logger.error(
                            "Move failed %s → %s: %s", src_folder, dst_folder, exc
                        )
                        self.error.emit(
                            f"Move failed ({src_folder} → {dst_folder}): {exc}"
                        )
                        done += len(uids)

                    self.progress.emit(done, total, f"Moved {done}/{total}")

        finally:
            try:
                client.logout()
            except Exception:
                pass

        self.finished.emit(done)


def _update_db_after_move(conn, folder_repo, msg_repo, uids, src_folder, dst_folder, account_id):
    """Update local DB: change folder_id on moved messages and recompute stats."""
    src = folder_repo.get_by_name(account_id, src_folder)
    dst = folder_repo.get_by_name(account_id, dst_folder)
    if not src or not dst or src.id is None or dst.id is None:
        return

    placeholders = ",".join("?" * len(uids))
    try:
        conn.execute(
            f"UPDATE messages SET folder_id = ? WHERE folder_id = ? AND uid IN ({placeholders})",
            [dst.id, src.id, *uids],
        )
        conn.commit()
        folder_repo.update_stats(src.id)
        folder_repo.update_stats(dst.id)
    except Exception as exc:
        logger.warning("DB update after move failed: %s", exc)
        conn.rollback()
