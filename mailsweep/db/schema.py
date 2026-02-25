"""Database schema — init_db() creates all tables and indexes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT    NOT NULL,
    host         TEXT    NOT NULL,
    port         INTEGER NOT NULL DEFAULT 993,
    username     TEXT    NOT NULL,
    auth_type    TEXT    NOT NULL DEFAULT 'password',
    use_ssl      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(host, username)
);

CREATE TABLE IF NOT EXISTS folders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    uid_validity    INTEGER NOT NULL DEFAULT 0,
    message_count   INTEGER NOT NULL DEFAULT 0,
    total_size_bytes INTEGER NOT NULL DEFAULT 0,
    last_scanned_at TEXT,
    UNIQUE(account_id, name)
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    uid              INTEGER NOT NULL,
    folder_id        INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    message_id       TEXT    NOT NULL DEFAULT '',
    from_addr        TEXT,
    to_addr          TEXT,
    subject          TEXT,
    date             TEXT,
    size_bytes       INTEGER NOT NULL DEFAULT 0,
    has_attachment   INTEGER NOT NULL DEFAULT 0,
    attachment_names TEXT    NOT NULL DEFAULT '[]',
    flags            TEXT    NOT NULL DEFAULT '[]',
    cached_at        TEXT    NOT NULL,
    UNIQUE(uid, folder_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_size       ON messages(size_bytes DESC);
CREATE INDEX IF NOT EXISTS idx_messages_from       ON messages(from_addr);
CREATE INDEX IF NOT EXISTS idx_messages_date       ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_attachment ON messages(has_attachment) WHERE has_attachment=1;
CREATE INDEX IF NOT EXISTS idx_messages_folder     ON messages(folder_id);
CREATE INDEX IF NOT EXISTS idx_messages_msgid      ON messages(message_id);
"""


def init_db(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Create (or open) the SQLite database, apply schema, return connection."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply incremental schema migrations for existing databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "to_addr" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN to_addr TEXT")
    if "message_id" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN message_id TEXT NOT NULL DEFAULT ''")

    # Composite index for identity-based lookups (unlabelled detection, dedup)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_identity "
        "ON messages(from_addr, subject, date, size_bytes)"
    )
