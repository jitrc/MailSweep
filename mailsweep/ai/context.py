"""Build a text summary of the mailbox DB for LLM consumption."""
from __future__ import annotations

import logging
import sqlite3

from mailsweep.db.repository import (
    AccountRepository,
    FolderRepository,
    MessageRepository,
)

logger = logging.getLogger(__name__)

# Target cap: ~8000 tokens ≈ ~32000 chars.  We budget per section.
_MAX_CHARS = 30000


def build_mailbox_context(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    folder_ids: list[int] | None = None,
) -> str:
    """Produce a markdown text block the LLM can reason over.

    Includes: account summary, folder tree with stats, top senders per folder,
    cross-folder sender overlap, and date ranges (live/dead).
    """
    acct_repo = AccountRepository(conn)
    folder_repo = FolderRepository(conn)
    msg_repo = MessageRepository(conn)

    parts: list[str] = []

    # ── Account summary ──────────────────────────────────────────────────────
    if account_id is not None:
        acct = acct_repo.get_by_id(account_id)
        if acct:
            folders = folder_repo.get_by_account(account_id)
            fids = [f.id for f in folders if f.id is not None]
            total_msgs = sum(f.message_count for f in folders)
            total_size = sum(f.total_size_bytes for f in folders)
            parts.append(
                f"## Mailbox Summary\n"
                f"Account: {acct.username} — {len(folders)} folders, "
                f"{total_msgs:,} messages, {_human(total_size)}"
            )

    # ── Folder tree ──────────────────────────────────────────────────────────
    target_account = account_id
    if target_account is None:
        # Pick the first account if none specified
        all_accts = acct_repo.get_all()
        if all_accts and all_accts[0].id is not None:
            target_account = all_accts[0].id

    if target_account is None:
        return "No accounts found in database."

    tree_rows = msg_repo.get_folder_tree_summary(target_account)

    if folder_ids:
        # Filter to only the requested folders and their children
        folder_names: set[str] = set()
        for row in tree_rows:
            if row["id"] in folder_ids:
                folder_names.add(row["name"])
        # Include children of selected folders
        all_names = {row["name"] for row in tree_rows}
        for name in list(folder_names):
            for n in all_names:
                if n.startswith(name + "/"):
                    folder_names.add(n)
        tree_rows = [r for r in tree_rows if r["name"] in folder_names]

    if tree_rows:
        lines = ["## Folder Tree"]
        lines.append(f"{'Folder':<45} {'Msgs':>8} {'Size':>10} {'Date Range'}")
        lines.append("-" * 85)
        for row in tree_rows:
            name = row["name"]
            # Indent based on path depth
            depth = name.count("/")
            indent = "  " * depth
            leaf = name.rsplit("/", 1)[-1] if "/" in name else name
            display = f"{indent}{leaf}"

            msg_count = row["message_count"] or 0
            size = row["total_size_bytes"] or 0
            min_d = _short_date(row["min_date"])
            max_d = _short_date(row["max_date"])
            date_range = f"{min_d} → {max_d}" if min_d and max_d else ""

            lines.append(f"{display:<45} {msg_count:>8,} {_human(size):>10} {date_range}")

        parts.append("\n".join(lines))

    # ── Top senders per folder ───────────────────────────────────────────────
    sender_lines = ["## Top Senders per Folder (top 5 each)"]
    char_budget = _MAX_CHARS // 3
    used = 0
    for row in tree_rows:
        if used > char_budget:
            sender_lines.append("... (truncated)")
            break
        fid = row["id"]
        if fid is None or (row["message_count"] or 0) == 0:
            continue
        top = msg_repo.get_top_senders_per_folder(fid, limit=5)
        if top:
            senders_str = ", ".join(
                f"{s['sender_email']} ({s['message_count']})" for s in top
            )
            line = f"{row['name']}: {senders_str}"
            sender_lines.append(line)
            used += len(line)

    if len(sender_lines) > 1:
        parts.append("\n".join(sender_lines))

    # ── Cross-folder sender overlap ──────────────────────────────────────────
    cross = msg_repo.get_cross_folder_senders(target_account, min_folders=2)
    if cross:
        overlap_lines = ["## Cross-Folder Sender Overlap"]
        for row in cross[:30]:
            overlap_lines.append(
                f"{row['sender_email']} appears in {row['folder_count']} folders: "
                f"{row['folder_counts']} (total: {row['total_count']})"
            )
        parts.append("\n".join(overlap_lines))

    # ── Date ranges (identify dead folders) ──────────────────────────────────
    dead_lines = ["## Possibly Dead Folders (no msgs in last 2 years)"]
    has_dead = False
    for row in tree_rows:
        max_d = row["max_date"]
        if max_d and max_d < "2024-01":
            dead_lines.append(
                f"{row['name']}: last message {_short_date(max_d)}, "
                f"{row['message_count'] or 0} msgs"
            )
            has_dead = True
    if has_dead:
        parts.append("\n".join(dead_lines))

    result = "\n\n".join(parts)
    if len(result) > _MAX_CHARS:
        result = result[:_MAX_CHARS] + "\n\n... (context truncated)"
    return result


def _human(size_bytes: int) -> str:
    """Quick human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _short_date(d: str | None) -> str:
    """Extract YYYY-MM from an ISO date string."""
    if not d:
        return ""
    return d[:7]
