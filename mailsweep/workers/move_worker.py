"""MoveWorker — IMAP move operations (RFC 6851 with copy+delete fallback)."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import connect
from mailsweep.models.account import Account

logger = logging.getLogger(__name__)

_COPY_BATCH_SIZE = 15  # Yahoo caps UID COPY at 15 UIDs per command
_COPY_RATE_LIMIT_WAIT = 1.0  # seconds to wait before retrying after a rate-limit error


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

        # Ensure each unique destination folder exists exactly once before
        # entering the SELECT loop (avoids redundant LIST calls per source folder).
        ensured_folders: set[str] = set()
        for op in moves:
            if op.dst_folder not in ensured_folders:
                _ensure_folder(client, op.dst_folder)
                ensured_folders.add(op.dst_folder)

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

                    # Chunk to avoid provider rate limits (Yahoo: [LIMIT] UID COPY)
                    for chunk_start in range(0, len(uids), _COPY_BATCH_SIZE):
                        if self._cancel_requested:
                            break

                        chunk = uids[chunk_start:chunk_start + _COPY_BATCH_SIZE]
                        self.progress.emit(done, total, f"Moving to {dst_folder}: {done}/{total}…")

                        for attempt in range(2):
                            try:
                                # Use COPY + flag + expunge — more reliable than IMAP MOVE
                                # across providers (Yahoo advertises MOVE but executes it unreliably).
                                client.copy(chunk, dst_folder)
                                client.set_flags(chunk, [b"\\Deleted"])
                                try:
                                    client.uid_expunge(chunk)
                                except Exception:
                                    client.expunge()

                                # Update local DB cache
                                if conn and folder_repo and msg_repo:
                                    _update_db_after_move(
                                        conn, folder_repo, msg_repo,
                                        chunk, src_folder, dst_folder, account.id,
                                    )

                                done += len(chunk)
                                logger.info(
                                    "Moved %d message(s) from %s to %s",
                                    len(chunk), src_folder, dst_folder,
                                )
                                break  # success

                            except Exception as exc:
                                if attempt == 0 and "LIMIT" in str(exc).upper():
                                    logger.warning(
                                        "Rate limit hit moving %s → %s, retrying in %.0fs…",
                                        src_folder, dst_folder, _COPY_RATE_LIMIT_WAIT,
                                    )
                                    time.sleep(_COPY_RATE_LIMIT_WAIT)
                                else:
                                    logger.error(
                                        "Move failed %s → %s: %s", src_folder, dst_folder, exc
                                    )
                                    self.error.emit(
                                        f"Move failed ({src_folder} → {dst_folder}): {exc}"
                                    )
                                    done += len(chunk)
                                    break

                        self.progress.emit(done, total, f"Moved {done}/{total}")

                        # Brief pause between chunks to avoid rate limits
                        if chunk_start + _COPY_BATCH_SIZE < len(uids):
                            time.sleep(1.0)

        finally:
            try:
                client.logout()
            except Exception:
                pass

        self.finished.emit(done)


def _ensure_folder(client, folder_name: str) -> None:
    """Create an IMAP folder if it doesn't already exist.

    Uses LIST to check existence so the currently-selected folder is not changed.
    """
    try:
        exists = bool(client.list_folders(pattern=folder_name))
    except Exception:
        exists = False
    if not exists:
        try:
            client.create_folder(folder_name)
            logger.info("Created IMAP folder: %s", folder_name)
        except Exception as exc:
            logger.warning("Could not create folder %s: %s", folder_name, exc)


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
