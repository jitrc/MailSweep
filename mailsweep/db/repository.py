"""Repository — all DB read/write operations for accounts, folders, messages."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from mailsweep.models.account import Account, AuthType
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, account: Account) -> Account:
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
        self._conn.commit()
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
        self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self._conn.commit()

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
        self._conn.commit()
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
        self._conn.execute("DELETE FROM messages WHERE folder_id = ?", (folder_id,))
        self._conn.execute(
            "UPDATE folders SET uid_validity=0, message_count=0, total_size_bytes=0, last_scanned_at=NULL WHERE id=?",
            (folder_id,),
        )
        self._conn.commit()

    def update_stats(self, folder_id: int) -> None:
        """Recompute message_count and total_size_bytes from messages table."""
        self._conn.execute(
            """
            UPDATE folders SET
                message_count    = (SELECT COUNT(*)    FROM messages WHERE folder_id = folders.id),
                total_size_bytes = (SELECT COALESCE(SUM(size_bytes), 0) FROM messages WHERE folder_id = folders.id)
            WHERE id = ?
            """,
            (folder_id,),
        )
        self._conn.commit()

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
        self._conn.executemany(
            """
            INSERT INTO messages
                (uid, folder_id, from_addr, subject, date, size_bytes,
                 has_attachment, attachment_names, flags, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid, folder_id) DO UPDATE SET
                from_addr        = excluded.from_addr,
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
                    m.uid, m.folder_id,
                    m.from_addr, m.subject,
                    m.date.isoformat() if m.date else None,
                    m.size_bytes, int(m.has_attachment),
                    m.attachment_names_json, m.flags_json, now,
                )
                for m in messages
            ],
        )
        self._conn.commit()

    def delete_uids(self, folder_id: int, uids: list[int]) -> None:
        if not uids:
            return
        placeholders = ",".join("?" * len(uids))
        self._conn.execute(
            f"DELETE FROM messages WHERE folder_id = ? AND uid IN ({placeholders})",
            [folder_id, *uids],
        )
        self._conn.commit()

    def get_uids_for_folder(self, folder_id: int) -> set[int]:
        rows = self._conn.execute(
            "SELECT uid FROM messages WHERE folder_id = ?", (folder_id,)
        ).fetchall()
        return {r["uid"] for r in rows}

    def query_messages(
        self,
        folder_ids: list[int] | None = None,
        from_filter: str = "",
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
        """Return per-sender aggregation: from_addr, count, total_size."""
        clauses: list[str] = []
        params: list[Any] = []
        if folder_ids:
            placeholders = ",".join("?" * len(folder_ids))
            clauses.append(f"folder_id IN ({placeholders})")
            params.extend(folder_ids)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT from_addr,
                   COUNT(*)        AS message_count,
                   SUM(size_bytes) AS total_size_bytes
            FROM messages
            {where}
            GROUP BY from_addr
            ORDER BY total_size_bytes DESC
            LIMIT 1000
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
