"""Repository — all DB read/write operations for accounts, folders, messages."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from mailsweep.models.account import Account, AuthType
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message

logger = logging.getLogger(__name__)


@contextmanager
def _safe_commit(conn: sqlite3.Connection) -> Generator[None, None, None]:
    """Commit on success, rollback on error."""
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, account: Account) -> Account:
        with _safe_commit(self._conn):
            cur = self._conn.execute(
                """
                INSERT INTO accounts (display_name, host, port, username, auth_type, use_ssl)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(host, username) DO UPDATE SET
                    display_name = excluded.display_name,
                    port         = excluded.port,
                    auth_type    = excluded.auth_type,
                    use_ssl      = excluded.use_ssl
                RETURNING id
                """,
                (
                    account.display_name, account.host, account.port,
                    account.username, account.auth_type.value, int(account.use_ssl),
                ),
            )
            row = cur.fetchone()
            account.id = row["id"]
        return account

    def get_all(self) -> list[Account]:
        rows = self._conn.execute("SELECT * FROM accounts ORDER BY display_name").fetchall()
        return [self._row_to_account(r) for r in rows]

    def get_by_id(self, account_id: int) -> Account | None:
        row = self._conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return self._row_to_account(row) if row else None

    def delete(self, account_id: int) -> None:
        with _safe_commit(self._conn):
            self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    def _row_to_account(self, row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            display_name=row["display_name"],
            host=row["host"],
            port=row["port"],
            username=row["username"],
            auth_type=AuthType(row["auth_type"]),
            use_ssl=bool(row["use_ssl"]),
        )


class FolderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, folder: Folder) -> Folder:
        with _safe_commit(self._conn):
            cur = self._conn.execute(
                """
                INSERT INTO folders (account_id, name, uid_validity, message_count, total_size_bytes, last_scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, name) DO UPDATE SET
                    uid_validity     = excluded.uid_validity,
                    message_count    = excluded.message_count,
                    total_size_bytes = excluded.total_size_bytes,
                    last_scanned_at  = excluded.last_scanned_at
                RETURNING id
                """,
                (
                    folder.account_id, folder.name, folder.uid_validity,
                    folder.message_count, folder.total_size_bytes,
                    folder.last_scanned_at.isoformat() if folder.last_scanned_at else None,
                ),
            )
            row = cur.fetchone()
            folder.id = row["id"]
        return folder

    def get_by_account(self, account_id: int) -> list[Folder]:
        rows = self._conn.execute(
            "SELECT * FROM folders WHERE account_id = ? ORDER BY total_size_bytes DESC",
            (account_id,),
        ).fetchall()
        return [self._row_to_folder(r) for r in rows]

    def get_by_id(self, folder_id: int) -> Folder | None:
        row = self._conn.execute(
            "SELECT * FROM folders WHERE id = ?", (folder_id,)
        ).fetchone()
        return self._row_to_folder(row) if row else None

    def get_by_name(self, account_id: int, name: str) -> Folder | None:
        row = self._conn.execute(
            "SELECT * FROM folders WHERE account_id = ? AND name = ?",
            (account_id, name),
        ).fetchone()
        return self._row_to_folder(row) if row else None

    def invalidate(self, folder_id: int) -> None:
        """Delete all messages for this folder (UID validity changed)."""
        with _safe_commit(self._conn):
            self._conn.execute("DELETE FROM messages WHERE folder_id = ?", (folder_id,))
            self._conn.execute(
                "UPDATE folders SET uid_validity=0, message_count=0, total_size_bytes=0, last_scanned_at=NULL WHERE id=?",
                (folder_id,),
            )

    def update_stats(self, folder_id: int) -> None:
        """Recompute message_count and total_size_bytes from messages table."""
        with _safe_commit(self._conn):
            self._conn.execute(
                """
                UPDATE folders SET
                    message_count    = (SELECT COUNT(*)    FROM messages WHERE folder_id = folders.id),
                    total_size_bytes = (SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE folder_id = folders.id)
                WHERE id = ?
                """,
                (folder_id,),
            )

    _ALL_MAIL_NAMES = {"[gmail]/all mail", "[google mail]/all mail"}

    def find_all_mail_folder(self, account_id: int) -> Folder | None:
        """Return the Gmail 'All Mail' folder, or None for non-Gmail accounts."""
        rows = self._conn.execute(
            "SELECT * FROM folders WHERE account_id = ?", (account_id,)
        ).fetchall()
        for row in rows:
            if row["name"].lower() in self._ALL_MAIL_NAMES:
                return self._row_to_folder(row)
        return None

    def _row_to_folder(self, row: sqlite3.Row) -> Folder:
        return Folder(
            id=row["id"],
            account_id=row["account_id"],
            name=row["name"],
            uid_validity=row["uid_validity"],
            message_count=row["message_count"],
            total_size_bytes=row["total_size_bytes"],
            last_scanned_at=(
                datetime.fromisoformat(row["last_scanned_at"])
                if row["last_scanned_at"] else None
            ),
        )


class MessageRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_batch(self, messages: list[Message]) -> None:
        """Batch upsert messages — fast path for scan worker."""
        now = _now_iso()
        with _safe_commit(self._conn):
            self._conn.executemany(
                """
                INSERT INTO messages
                    (uid, folder_id, message_id, in_reply_to, thread_id,
                     from_addr, to_addr, subject, date,
                     size_bytes, has_attachment, attachment_names, flags, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid, folder_id) DO UPDATE SET
                    message_id       = excluded.message_id,
                    in_reply_to      = excluded.in_reply_to,
                    thread_id        = excluded.thread_id,
                    from_addr        = excluded.from_addr,
                    to_addr          = excluded.to_addr,
                    subject          = excluded.subject,
                    date             = excluded.date,
                    size_bytes       = excluded.size_bytes,
                    has_attachment   = excluded.has_attachment,
                    attachment_names = excluded.attachment_names,
                    flags            = excluded.flags,
                    cached_at        = excluded.cached_at
                """,
                [
                    (
                        m.uid, m.folder_id, m.message_id,
                        m.in_reply_to, m.thread_id,
                        m.from_addr, m.to_addr, m.subject,
                        m.date.isoformat() if m.date else None,
                        m.size_bytes, int(m.has_attachment),
                        m.attachment_names_json, m.flags_json, now,
                    )
                    for m in messages
                ],
            )

    def delete_uids(self, folder_id: int, uids: list[int]) -> None:
        if not uids:
            return
        placeholders = ",".join("?" * len(uids))
        with _safe_commit(self._conn):
            self._conn.execute(
                f"DELETE FROM messages WHERE folder_id = ? AND uid IN ({placeholders})",
                [folder_id, *uids],
            )

    def get_uids_for_folder(self, folder_id: int) -> set[int]:
        rows = self._conn.execute(
            "SELECT uid FROM messages WHERE folder_id = ?", (folder_id,)
        ).fetchall()
        return {r["uid"] for r in rows}

    def query_messages(
        self,
        folder_ids: list[int] | None = None,
        from_filter: str = "",
        to_filter: str = "",
        subject_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        size_min: int = 0,
        size_max: int = 0,
        has_attachment: bool | None = None,
        order_by: str = "size_bytes DESC",
        limit: int = 5000,
    ) -> list[Message]:
        clauses: list[str] = []
        params: list[Any] = []

        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            clauses.append(f"m.folder_id IN ({placeholders})")
            params.extend(folder_ids)

        if from_filter:
            clauses.append("LOWER(m.from_addr) LIKE ?")
            params.append(f"%{from_filter.lower()}%")

        if to_filter:
            clauses.append("LOWER(m.to_addr) LIKE ?")
            params.append(f"%{to_filter.lower()}%")

        if subject_filter:
            clauses.append("LOWER(m.subject) LIKE ?")
            params.append(f"%{subject_filter.lower()}%")

        if date_from:
            clauses.append("m.date >= ?")
            params.append(date_from)

        if date_to:
            clauses.append("m.date <= ?")
            params.append(date_to)

        if size_min > 0:
            clauses.append("m.size_bytes >= ?")
            params.append(size_min)

        if size_max > 0:
            clauses.append("m.size_bytes <= ?")
            params.append(size_max)

        if has_attachment is True:
            clauses.append("m.has_attachment = 1")
        elif has_attachment is False:
            clauses.append("m.has_attachment = 0")

        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        # Validate order_by to prevent SQL injection
        allowed_order = {
            "size_bytes DESC", "size_bytes ASC",
            "date DESC", "date ASC",
            "from_addr ASC", "from_addr DESC",
            "to_addr ASC", "to_addr DESC",
            "subject ASC",
        }
        if order_by not in allowed_order:
            order_by = "size_bytes DESC"

        sql = f"""
            SELECT m.*, f.name AS folder_name
            FROM messages m
            JOIN folders f ON f.id = m.folder_id
            {where}
            ORDER BY m.{order_by}
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [Message.from_row(dict(r)) for r in rows]

    def get_sender_summary(
        self, folder_ids: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Return per-sender aggregation grouped by email address.

        from_addr may be 'Name <email>' or just 'email'. We extract the
        email portion so 'Alice <a@b.com>' and 'A <a@b.com>' merge into
        one group. The display name shown is the most common variant.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            clauses.append(f"folder_id IN ({placeholders})")
            params.extend(folder_ids)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        # Extract email: take substring between < and >, else use full from_addr
        sql = f"""
            SELECT
                CASE WHEN INSTR(from_addr, '<') > 0
                     THEN LOWER(SUBSTR(from_addr,
                                       INSTR(from_addr, '<') + 1,
                                       INSTR(from_addr, '>') - INSTR(from_addr, '<') - 1))
                     ELSE LOWER(from_addr)
                END AS sender_email,
                from_addr,
                COUNT(*)        AS message_count,
                SUM(size_bytes) AS total_size_bytes
            FROM messages
            {where}
            GROUP BY sender_email
            ORDER BY total_size_bytes DESC
            LIMIT 1000
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_receiver_summary(
        self, folder_ids: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Return per-receiver aggregation grouped by email address.

        Same extraction logic as get_sender_summary but on to_addr.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            clauses.append(f"folder_id IN ({placeholders})")
            params.extend(folder_ids)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT
                CASE WHEN INSTR(to_addr, '<') > 0
                     THEN LOWER(SUBSTR(to_addr,
                                       INSTR(to_addr, '<') + 1,
                                       INSTR(to_addr, '>') - INSTR(to_addr, '<') - 1))
                     ELSE LOWER(to_addr)
                END AS receiver_email,
                to_addr,
                COUNT(*)        AS message_count,
                SUM(size_bytes) AS total_size_bytes
            FROM messages
            {where}
            GROUP BY receiver_email
            ORDER BY total_size_bytes DESC
            LIMIT 1000
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_dedup_total_size(
        self, folder_ids: list[int] | None = None
    ) -> tuple[int, int]:
        """Return (dedup_size_bytes, dedup_count) after removing duplicate messages.

        Gmail labels cause the same message to appear in multiple folders.
        We deduplicate by message_id when available, falling back to
        (from_addr, subject, date, size_bytes) for messages without one.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            clauses.append(f"folder_id IN ({placeholders})")
            params.extend(folder_ids)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        where_and = ("AND " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT COALESCE(SUM(size_bytes), 0) AS total,
                   COUNT(*) AS cnt
            FROM (
                SELECT DISTINCT message_id, size_bytes
                FROM messages
                WHERE message_id != '' {where_and}
                UNION ALL
                SELECT DISTINCT from_addr || subject || date, size_bytes
                FROM messages
                WHERE message_id = '' {where_and}
            )
        """
        all_params = params + params
        row = self._conn.execute(sql, all_params).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    # ── Unlabelled (archived-only) queries ─────────────────────────────────

    def _unlabelled_not_exists(self, other_folder_ids: list[int]) -> tuple[str, list[Any]]:
        """Return (SQL fragment, params) for the NOT EXISTS subquery.

        Uses message_id for matching when available (reliable, globally unique).
        Falls back to identity tuple for messages without message_id.
        """
        placeholders = ",".join("?" * len(other_folder_ids))
        fragment = (
            "("
            # Messages WITH message_id: match by message_id
            "  (m.message_id != '' AND NOT EXISTS ("
            "    SELECT 1 FROM messages o"
            f"    WHERE o.folder_id IN ({placeholders})"
            "      AND o.message_id = m.message_id"
            "  ))"
            "  OR"
            # Messages WITHOUT message_id: fall back to identity tuple
            "  (m.message_id = '' AND NOT EXISTS ("
            "    SELECT 1 FROM messages o"
            f"    WHERE o.folder_id IN ({placeholders})"
            "      AND o.from_addr IS m.from_addr"
            "      AND o.subject   IS m.subject"
            "      AND o.date      IS m.date"
            "      AND o.size_bytes = m.size_bytes"
            "  ))"
            ")"
        )
        return fragment, list(other_folder_ids) + list(other_folder_ids)

    def _unlabelled_not_exists_thread(self, other_folder_ids: list[int]) -> tuple[str, list[Any]]:
        """Return (SQL fragment, params) for In-Reply-To chain mode.

        A message is NOT unlabelled if any message in a labelled folder is:
        - its parent (other.message_id = m.in_reply_to)
        - its child (other.in_reply_to = m.message_id)
        - itself (same message_id)
        Falls back to identity-tuple for messages without message_id.
        """
        placeholders = ",".join("?" * len(other_folder_ids))
        ids = list(other_folder_ids)
        fragment = (
            "("
            # Messages WITH message_id: match by message_id or reply chain
            "  (m.message_id != '' AND NOT EXISTS ("
            "    SELECT 1 FROM messages o"
            f"    WHERE o.folder_id IN ({placeholders})"
            "      AND ("
            "        o.message_id = m.message_id"
            "        OR (m.in_reply_to != '' AND o.message_id = m.in_reply_to)"
            "        OR (o.in_reply_to != '' AND o.in_reply_to = m.message_id)"
            "      )"
            "  ))"
            "  OR"
            # Messages WITHOUT message_id: fall back to identity tuple
            "  (m.message_id = '' AND NOT EXISTS ("
            "    SELECT 1 FROM messages o"
            f"    WHERE o.folder_id IN ({placeholders})"
            "      AND o.from_addr IS m.from_addr"
            "      AND o.subject   IS m.subject"
            "      AND o.date      IS m.date"
            "      AND o.size_bytes = m.size_bytes"
            "  ))"
            ")"
        )
        return fragment, ids + ids

    def _unlabelled_not_exists_gmail_thread(self, other_folder_ids: list[int]) -> tuple[str, list[Any]]:
        """Return (SQL fragment, params) for Gmail Thread ID mode.

        Messages with thread_id != 0: unlabelled if NO message with the same
        thread_id exists in a labelled folder.
        Messages with thread_id == 0: fall back to message_id / identity-tuple.
        """
        placeholders = ",".join("?" * len(other_folder_ids))
        ids = list(other_folder_ids)
        # Build the fallback (no_thread) fragment for thread_id=0 messages
        fallback_fragment, fallback_params = self._unlabelled_not_exists(other_folder_ids)
        fragment = (
            "("
            # Messages WITH thread_id: match by thread_id
            "  (m.thread_id != 0 AND NOT EXISTS ("
            "    SELECT 1 FROM messages o"
            f"    WHERE o.folder_id IN ({placeholders})"
            "      AND o.thread_id = m.thread_id"
            "  ))"
            "  OR"
            # Messages WITHOUT thread_id: fall back to no_thread logic
            f"  (m.thread_id = 0 AND {fallback_fragment})"
            ")"
        )
        return fragment, ids + fallback_params

    def _get_unlabelled_not_exists(self, other_folder_ids: list[int], mode: str = "no_thread") -> tuple[str, list[Any]]:
        """Dispatch to the appropriate NOT EXISTS builder based on mode."""
        if mode == "in_reply_to":
            return self._unlabelled_not_exists_thread(other_folder_ids)
        elif mode == "gmail_thread":
            return self._unlabelled_not_exists_gmail_thread(other_folder_ids)
        else:
            return self._unlabelled_not_exists(other_folder_ids)

    def get_unlabelled_stats(
        self,
        all_mail_folder_id: int,
        other_folder_ids: list[int],
        mode: str = "no_thread",
    ) -> tuple[int, int]:
        """Return (count, total_size) of messages only in All Mail (no labels).

        If other_folder_ids is empty, all All Mail messages are "unlabelled".
        mode: "no_thread" | "in_reply_to" | "gmail_thread"
        """
        if not other_folder_ids:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) "
                "FROM messages WHERE folder_id = ?",
                (all_mail_folder_id,),
            ).fetchone()
            return (row[0], row[1]) if row else (0, 0)

        not_exists, ne_params = self._get_unlabelled_not_exists(other_folder_ids, mode)
        sql = (
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) "
            f"FROM messages m WHERE m.folder_id = ? AND {not_exists}"
        )
        row = self._conn.execute(sql, [all_mail_folder_id, *ne_params]).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def query_unlabelled_messages(
        self,
        all_mail_folder_id: int,
        other_folder_ids: list[int],
        from_filter: str = "",
        to_filter: str = "",
        subject_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        size_min: int = 0,
        size_max: int = 0,
        has_attachment: bool | None = None,
        order_by: str = "size_bytes DESC",
        limit: int = 5000,
        mode: str = "no_thread",
    ) -> list[Message]:
        """Query messages that exist only in All Mail (no other labels).

        mode: "no_thread" | "in_reply_to" | "gmail_thread"
        """
        clauses: list[str] = ["m.folder_id = ?"]
        params: list[Any] = [all_mail_folder_id]

        if other_folder_ids:
            not_exists, ne_params = self._get_unlabelled_not_exists(other_folder_ids, mode)
            clauses.append(not_exists)
            params.extend(ne_params)

        if from_filter:
            clauses.append("LOWER(m.from_addr) LIKE ?")
            params.append(f"%{from_filter.lower()}%")
        if to_filter:
            clauses.append("LOWER(m.to_addr) LIKE ?")
            params.append(f"%{to_filter.lower()}%")
        if subject_filter:
            clauses.append("LOWER(m.subject) LIKE ?")
            params.append(f"%{subject_filter.lower()}%")
        if date_from:
            clauses.append("m.date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("m.date <= ?")
            params.append(date_to)
        if size_min > 0:
            clauses.append("m.size_bytes >= ?")
            params.append(size_min)
        if size_max > 0:
            clauses.append("m.size_bytes <= ?")
            params.append(size_max)
        if has_attachment is True:
            clauses.append("m.has_attachment = 1")
        elif has_attachment is False:
            clauses.append("m.has_attachment = 0")

        where = "WHERE " + " AND ".join(clauses)

        allowed_order = {
            "size_bytes DESC", "size_bytes ASC",
            "date DESC", "date ASC",
            "from_addr ASC", "from_addr DESC",
            "to_addr ASC", "to_addr DESC",
            "subject ASC",
        }
        if order_by not in allowed_order:
            order_by = "size_bytes DESC"

        sql = f"""
            SELECT m.*, f.name AS folder_name
            FROM messages m
            JOIN folders f ON f.id = m.folder_id
            {where}
            ORDER BY m.{order_by}
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [Message.from_row(dict(r)) for r in rows]

    def get_folder_tree_summary(self, account_id: int) -> list[dict]:
        """Return folder name, message_count, total_size_bytes, min(date), max(date) for each folder."""
        rows = self._conn.execute(
            """
            SELECT f.id, f.name, f.message_count, f.total_size_bytes,
                   MIN(m.date) AS min_date, MAX(m.date) AS max_date
            FROM folders f
            LEFT JOIN messages m ON m.folder_id = f.id
            WHERE f.account_id = ?
            GROUP BY f.id
            ORDER BY f.name
            """,
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_cross_folder_senders(self, account_id: int, min_folders: int = 2) -> list[dict]:
        """Find senders that appear in multiple folders (potential misfilings).

        Returns list of dicts with sender_email, folder_counts (JSON), total_count.
        """
        rows = self._conn.execute(
            """
            SELECT sender_email, COUNT(DISTINCT f.name) AS folder_count,
                   GROUP_CONCAT(DISTINCT f.name || ':' || cnt) AS folder_counts,
                   SUM(cnt) AS total_count
            FROM (
                SELECT
                    CASE WHEN INSTR(m.from_addr, '<') > 0
                         THEN LOWER(SUBSTR(m.from_addr,
                                           INSTR(m.from_addr, '<') + 1,
                                           INSTR(m.from_addr, '>') - INSTR(m.from_addr, '<') - 1))
                         ELSE LOWER(m.from_addr)
                    END AS sender_email,
                    m.folder_id,
                    COUNT(*) AS cnt
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE f.account_id = ?
                GROUP BY sender_email, m.folder_id
            ) sub
            JOIN folders f ON f.id = sub.folder_id
            GROUP BY sender_email
            HAVING folder_count >= ?
            ORDER BY folder_count DESC, total_count DESC
            LIMIT 100
            """,
            (account_id, min_folders),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_top_senders_per_folder(self, folder_id: int, limit: int = 5) -> list[dict]:
        """Return top senders for a specific folder."""
        rows = self._conn.execute(
            """
            SELECT
                CASE WHEN INSTR(from_addr, '<') > 0
                     THEN LOWER(SUBSTR(from_addr,
                                       INSTR(from_addr, '<') + 1,
                                       INSTR(from_addr, '>') - INSTR(from_addr, '<') - 1))
                     ELSE LOWER(from_addr)
                END AS sender_email,
                COUNT(*) AS message_count
            FROM messages
            WHERE folder_id = ?
            GROUP BY sender_email
            ORDER BY message_count DESC
            LIMIT ?
            """,
            (folder_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_detached_originals(self, account_id: int) -> tuple[list[Message], int, int]:
        """Find original messages that have a smaller detached copy.

        Thunderbird's "Detach Attachment" leaves the original (with attachment)
        on the server alongside the stripped copy.  This finds pairs sharing
        (from_addr, subject, date) where one is >1.5x larger.

        Returns both the originals (tagged "Original") and copies (tagged
        "Detached Copy") grouped by pair, so the user can verify before deleting.

        Returns (messages, original_count, original_total_bytes).
        """
        sql = """
            WITH non_gmail AS (
                SELECT m.* FROM messages m
                JOIN folders f ON m.folder_id = f.id
                WHERE f.account_id = ?
                  AND f.name NOT LIKE '[Gmail]/%%'
            ),
            pairs AS (
                SELECT a.id AS copy_id, b.id AS orig_id
                FROM non_gmail a
                JOIN non_gmail b
                  ON a.from_addr = b.from_addr
                 AND a.date = b.date
                 AND a.subject = b.subject
                 AND a.size_bytes < b.size_bytes
                 AND b.size_bytes > a.size_bytes * 1.5
            )
            SELECT DISTINCT m.*, f.name AS folder_name,
                   CASE WHEN m.id IN (SELECT orig_id FROM pairs)
                        THEN 'Original'
                        ELSE 'Detached Copy'
                   END AS tag
            FROM (
                SELECT orig_id AS mid FROM pairs
                UNION
                SELECT copy_id AS mid FROM pairs
            ) ids
            JOIN messages m ON m.id = ids.mid
            JOIN folders f ON f.id = m.folder_id
            ORDER BY m.from_addr, m.subject, m.date, m.size_bytes DESC
        """
        rows = self._conn.execute(sql, (account_id,)).fetchall()
        messages = []
        for r in rows:
            row_dict = dict(r)
            tag = row_dict.pop("tag", "")
            msg = Message.from_row(row_dict)
            msg.tag = tag
            messages.append(msg)
        originals = [m for m in messages if m.tag == "Original"]
        total_bytes = sum(m.size_bytes for m in originals)
        return messages, len(originals), total_bytes

    def find_cross_label_duplicates(
        self,
        account_id: int,
        skip_folder_ids: list[int] | None = None,
    ) -> tuple[list[Message], int, int]:
        """Find messages that appear in 2+ folders (cross-label duplicates).

        Returns (messages, group_count, total_duplicate_bytes) where
        duplicate bytes = sum of all copies minus one per group.
        """
        skip_clause = ""
        params: list[Any] = [account_id]
        if skip_folder_ids:
            placeholders = ",".join("?" * len(skip_folder_ids))
            skip_clause = f"AND f.id NOT IN ({placeholders})"
            params.extend(skip_folder_ids)

        # Messages WITH message_id: group by message_id
        # Messages WITHOUT message_id: group by identity tuple
        sql = f"""
            WITH eligible AS (
                SELECT m.*, f.name AS folder_name
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE f.account_id = ? {skip_clause}
            ),
            -- Groups with message_id
            mid_groups AS (
                SELECT message_id AS grp_key,
                       COUNT(DISTINCT folder_id) AS folder_cnt,
                       MAX(size_bytes) AS max_size
                FROM eligible
                WHERE message_id != ''
                GROUP BY message_id
                HAVING COUNT(DISTINCT folder_id) >= 2
            ),
            -- Groups without message_id (identity tuple)
            ident_groups AS (
                SELECT from_addr || '|' || subject || '|' || date || '|' || size_bytes AS grp_key,
                       COUNT(DISTINCT folder_id) AS folder_cnt,
                       MAX(size_bytes) AS max_size
                FROM eligible
                WHERE message_id = ''
                GROUP BY from_addr, subject, date, size_bytes
                HAVING COUNT(DISTINCT folder_id) >= 2
            ),
            -- All matching messages with their group info
            tagged_mid AS (
                SELECT e.*, g.folder_cnt,
                       e.message_id AS grp_key
                FROM eligible e
                JOIN mid_groups g ON g.grp_key = e.message_id
            ),
            tagged_ident AS (
                SELECT e.*, g.folder_cnt,
                       e.from_addr || '|' || e.subject || '|' || e.date || '|' || e.size_bytes AS grp_key
                FROM eligible e
                JOIN ident_groups g ON g.grp_key = (e.from_addr || '|' || e.subject || '|' || e.date || '|' || e.size_bytes)
                WHERE e.message_id = ''
            ),
            combined AS (
                SELECT * FROM tagged_mid
                UNION ALL
                SELECT * FROM tagged_ident
            )
            SELECT * FROM combined
            ORDER BY size_bytes DESC, grp_key, folder_name
        """
        rows = self._conn.execute(sql, params).fetchall()

        messages: list[Message] = []
        group_sizes: dict[str, list[int]] = {}
        for r in rows:
            row_dict = dict(r)
            folder_cnt = row_dict.pop("folder_cnt")
            grp_key = row_dict.pop("grp_key")
            msg = Message.from_row(row_dict)
            msg.tag = f"{folder_cnt} labels"
            messages.append(msg)
            group_sizes.setdefault(grp_key, []).append(msg.size_bytes)

        group_count = len(group_sizes)
        # Duplicate bytes = total of all copies minus one (the smallest) per group
        total_duplicate_bytes = 0
        for sizes in group_sizes.values():
            total_duplicate_bytes += sum(sizes) - min(sizes)

        return messages, group_count, total_duplicate_bytes

    def get_folders_for_message(self, msg: Message, include_thread: bool = False) -> list[str]:
        """Return all folder names containing the same physical message.

        Uses message_id for matching when available; falls back to identity tuple.
        If include_thread is True and thread_id is set, also include folders
        from thread-mate messages.
        """
        if msg.message_id:
            rows = self._conn.execute(
                """
                SELECT DISTINCT f.name
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE m.message_id = ?
                ORDER BY f.name
                """,
                (msg.message_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT DISTINCT f.name
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE m.from_addr IS ?
                  AND m.subject   IS ?
                  AND m.date      IS ?
                  AND m.size_bytes = ?
                ORDER BY f.name
                """,
                (
                    msg.from_addr,
                    msg.subject,
                    msg.date.isoformat() if msg.date else None,
                    msg.size_bytes,
                ),
            ).fetchall()
        names = {r["name"] for r in rows}

        if include_thread and msg.thread_id:
            thread_rows = self._conn.execute(
                """
                SELECT DISTINCT f.name
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE m.thread_id = ?
                ORDER BY f.name
                """,
                (msg.thread_id,),
            ).fetchall()
            names.update(r["name"] for r in thread_rows)

        return sorted(names)

    def get_message_copies(self, msg: Message) -> list[Message]:
        """Return all copies of a message across folders (uid, folder_id, folder_name).

        Uses message_id for matching when available; falls back to identity tuple.
        """
        if msg.message_id:
            rows = self._conn.execute(
                """
                SELECT m.*, f.name AS folder_name
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE m.message_id = ?
                ORDER BY f.name
                """,
                (msg.message_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT m.*, f.name AS folder_name
                FROM messages m
                JOIN folders f ON f.id = m.folder_id
                WHERE m.from_addr IS ?
                  AND m.subject   IS ?
                  AND m.date      IS ?
                  AND m.size_bytes = ?
                ORDER BY f.name
                """,
                (
                    msg.from_addr,
                    msg.subject,
                    msg.date.isoformat() if msg.date else None,
                    msg.size_bytes,
                ),
            ).fetchall()
        return [Message.from_row(dict(r)) for r in rows]
