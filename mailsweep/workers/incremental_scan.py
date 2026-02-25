"""Incremental scan helpers — UIDVALIDITY + CONDSTORE support."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from imapclient import IMAPClient
    from mailsweep.db.repository import MessageRepository

logger = logging.getLogger(__name__)


def get_new_deleted_uids(
    client: "IMAPClient",
    folder_id: int,
    msg_repo: "MessageRepository",
) -> tuple[list[int], list[int]]:
    """
    Return (new_uids, deleted_uids) for an incremental scan.

    Compares server UID set (NOT DELETED) vs cached UIDs in DB.
    """
    server_uids: set[int] = set(client.search(["NOT", "DELETED"]))
    cached_uids: set[int] = msg_repo.get_uids_for_folder(folder_id)

    new_uids = sorted(server_uids - cached_uids)
    deleted_uids = sorted(cached_uids - server_uids)

    logger.debug(
        "Incremental scan: %d new, %d deleted for folder_id=%d",
        len(new_uids), len(deleted_uids), folder_id,
    )
    return new_uids, deleted_uids


def supports_condstore(client: "IMAPClient") -> bool:
    """Check whether the server advertises CONDSTORE capability."""
    try:
        caps = client.capabilities()
        return b"CONDSTORE" in caps or "CONDSTORE" in caps
    except Exception:
        return False
