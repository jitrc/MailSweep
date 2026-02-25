"""MailSweep CLI — scan a mailbox and print folder sizes (Phase 1 deliverable)."""
from __future__ import annotations

import argparse
import getpass
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from mailsweep.config import DB_PATH
from mailsweep.db.repository import AccountRepository, FolderRepository, MessageRepository
from mailsweep.db.schema import init_db
from mailsweep.imap.connection import IMAPConnectionError, connect, list_folders
from mailsweep.models.account import Account, AuthType
from mailsweep.models.folder import Folder
from mailsweep.utils.keyring_store import set_password
from mailsweep.utils.size_fmt import human_size
from mailsweep.workers.scan_worker import ScanWorker

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mailsweep-cli",
        description="MailSweep — IMAP Mailbox Analyzer (CLI)",
    )
    p.add_argument("--host", required=True, help="IMAP server hostname")
    p.add_argument("--port", type=int, default=993, help="IMAP port (default 993)")
    p.add_argument("--username", required=True, help="IMAP username / email")
    p.add_argument("--no-ssl", action="store_true", help="Disable SSL/TLS")
    p.add_argument("--folders", nargs="*", help="Folders to scan (default: all)")
    p.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    password = getpass.getpass(f"Password for {args.username}@{args.host}: ")
    set_password(args.username, args.host, password)

    conn = init_db(args.db)
    account_repo = AccountRepository(conn)
    folder_repo = FolderRepository(conn)
    msg_repo = MessageRepository(conn)

    account = Account(
        display_name=f"{args.username}@{args.host}",
        host=args.host,
        port=args.port,
        username=args.username,
        auth_type=AuthType.PASSWORD,
        use_ssl=not args.no_ssl,
    )
    account = account_repo.upsert(account)
    assert account.id is not None

    print(f"Connecting to {args.host}:{args.port}…")
    try:
        client = connect(account)
    except IMAPConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Connected. Listing folders…")
    all_folder_names = list_folders(client)
    if args.folders:
        folder_names = [f for f in all_folder_names if f in args.folders]
    else:
        folder_names = all_folder_names

    print(f"Scanning {len(folder_names)} folder(s)…\n")

    results: list[tuple[str, int, int]] = []  # (name, count, size)

    for fname in folder_names:
        # Get or create folder record
        folder = folder_repo.get_by_name(account.id, fname)
        if not folder:
            folder = Folder(account_id=account.id, name=fname)
            folder = folder_repo.upsert(folder)
        assert folder.id is not None

        # Check UID validity
        try:
            status = client.select_folder(fname, readonly=True)
            server_uidvalidity = int(status.get(b"UIDVALIDITY", 0))
            if folder.uid_validity and folder.uid_validity != server_uidvalidity:
                print(f"  [{fname}] UID validity changed — invalidating cache")
                folder_repo.invalidate(folder.id)
                folder.uid_validity = 0
        except Exception as exc:
            print(f"  [{fname}] Cannot select: {exc} — skipping")
            continue

        def on_batch(messages, _fid=folder.id):
            msg_repo.upsert_batch(messages)

        def on_progress(done, total, _fn=fname):
            print(f"  [{_fn}] {done}/{total}\r", end="", flush=True)

        worker = ScanWorker(
            client=client,
            folder_id=folder.id,
            folder_name=fname,
            on_batch=on_batch,
            on_progress=on_progress,
        )
        try:
            messages = worker.run()
        except Exception as exc:
            print(f"\n  [{fname}] Scan error: {exc}")
            continue

        # Update folder metadata
        folder.uid_validity = server_uidvalidity
        folder.last_scanned_at = datetime.now(timezone.utc)
        folder_repo.upsert(folder)
        folder_repo.update_stats(folder.id)

        updated = folder_repo.get_by_id(folder.id)
        count = updated.message_count if updated else len(messages)
        size = updated.total_size_bytes if updated else sum(m.size_bytes for m in messages)
        results.append((fname, count, size))
        print(f"\n  [{fname}] {count} messages, {human_size(size)}")

    client.logout()

    # Summary table
    print("\n" + "=" * 60)
    print(f"{'FOLDER':<40} {'MESSAGES':>8} {'SIZE':>10}")
    print("-" * 60)
    total_size = 0
    for fname, count, size in sorted(results, key=lambda x: x[2], reverse=True):
        print(f"{fname:<40} {count:>8} {human_size(size):>10}")
        total_size += size
    print("=" * 60)
    print(f"{'TOTAL':<40} {'':>8} {human_size(total_size):>10}")
    conn.close()


if __name__ == "__main__":
    main()
