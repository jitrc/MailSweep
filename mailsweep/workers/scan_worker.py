"""ScanWorker — fetches ENVELOPE+SIZE+BODYSTRUCTURE for all messages in a folder.

Can be used as a plain class (Phase 1 CLI) or as a QObject moved to QThread (Phase 2 GUI).
"""
from __future__ import annotations

import email.header
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from imapclient import IMAPClient

from mailsweep.models.message import Message

logger = logging.getLogger(__name__)

BATCH_SIZE = 500

# IMAP fetch items
FETCH_ITEMS = [b"ENVELOPE", b"RFC822.SIZE", b"BODYSTRUCTURE", b"FLAGS", b"X-GM-THRID"]


class ScanWorker:
    """
    Scans one IMAP folder: fetches metadata for all messages and calls
    `on_batch(messages)` for each batch of BATCH_SIZE.

    Not a QObject yet — Phase 2 wraps it.
    """

    def __init__(
        self,
        client: IMAPClient,
        folder_id: int,
        folder_name: str,
        on_batch: Callable[[list[Message]], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self._client = client
        self._folder_id = folder_id
        self._folder_name = folder_name
        self._on_batch = on_batch or (lambda msgs: None)
        self._on_progress = on_progress or (lambda done, total: None)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self, uids: list[int] | None = None) -> list[Message]:
        """
        Scan the folder.  If *uids* is given, fetch only those UIDs (incremental).
        Otherwise fetch all non-deleted UIDs (full scan).
        Returns fetched Message objects.  Raises on connection error.
        """
        self._client.select_folder(self._folder_name, readonly=True)
        if uids is not None:
            all_uids = uids
        else:
            all_uids = self._client.search(["NOT", "DELETED"])
        total = len(all_uids)
        logger.info("Scanning %s: %d messages", self._folder_name, total)

        all_messages: list[Message] = []
        done = 0

        for batch_start in range(0, total, BATCH_SIZE):
            if self._cancel_requested:
                logger.info("Scan cancelled at uid batch %d/%d", done, total)
                break

            batch_uids = all_uids[batch_start: batch_start + BATCH_SIZE]
            try:
                fetch_data = self._client.fetch(batch_uids, FETCH_ITEMS)
            except Exception as exc:
                logger.error("FETCH failed for %s batch %d: %s", self._folder_name, batch_start, exc)
                raise

            batch_messages = []
            for uid, data in fetch_data.items():
                msg = _parse_fetch_response(uid, self._folder_id, data)
                if msg:
                    batch_messages.append(msg)

            all_messages.extend(batch_messages)
            self._on_batch(batch_messages)
            done += len(batch_uids)
            self._on_progress(done, total)

        return all_messages


# ── IMAP response parsers ─────────────────────────────────────────────────────

def _parse_fetch_response(uid: int, folder_id: int, data: dict) -> Message | None:
    try:
        envelope = data.get(b"ENVELOPE")
        size = data.get(b"RFC822.SIZE", 0)
        bodystructure = data.get(b"BODYSTRUCTURE")
        flags = [f.decode() if isinstance(f, bytes) else str(f) for f in data.get(b"FLAGS", [])]

        # imapclient 3.x returns an Envelope object with named attributes:
        #   .date (datetime|None), .subject (bytes), .from_ (tuple[Address]|None)
        # Address has: .name (bytes), .route, .mailbox (bytes), .host (bytes)
        if envelope is not None:
            from_addr = _envelope_addr(getattr(envelope, "from_", None))
            to_addr = _envelope_addr(getattr(envelope, "to", None))
            subject = _decode_header(getattr(envelope, "subject", b""))
            message_id = _b(getattr(envelope, "message_id", b""))
            in_reply_to = _b(getattr(envelope, "in_reply_to", b""))
            raw_date = getattr(envelope, "date", None)
            # .date is already a datetime in imapclient 3.x
            if isinstance(raw_date, datetime):
                date = raw_date
            else:
                date = _parse_date(raw_date)
        else:
            from_addr = ""
            to_addr = ""
            subject = ""
            message_id = ""
            in_reply_to = ""
            date = None

        thread_id = data.get(b"X-GM-THRID", 0) or 0

        has_attachment, attachment_names = _parse_bodystructure(bodystructure)

        return Message(
            uid=uid,
            folder_id=folder_id,
            message_id=message_id,
            in_reply_to=in_reply_to,
            thread_id=thread_id,
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            date=date,
            size_bytes=size or 0,
            has_attachment=has_attachment,
            attachment_names=attachment_names,
            flags=flags,
        )
    except Exception as exc:
        logger.warning("Failed to parse message uid=%d: %s", uid, exc)
        return None


def _envelope_addr(addr_list: Any) -> str:
    """Extract 'Name <email>' from an ENVELOPE address list.

    imapclient 3.x: addr_list is tuple[Address, ...] or None.
    Address has .name, .mailbox, .host (all bytes or None).
    """
    if not addr_list:
        return ""
    try:
        addr = addr_list[0]
        # Support both attribute access (imapclient 3.x Address) and index access (raw tuple)
        name_raw = getattr(addr, "name", None) or (addr[0] if not hasattr(addr, "name") else None)
        mbox_raw = getattr(addr, "mailbox", None) or (addr[2] if not hasattr(addr, "mailbox") else None)
        host_raw = getattr(addr, "host", None) or (addr[3] if not hasattr(addr, "host") else None)

        name = _decode_header(name_raw) if name_raw else ""
        mailbox = mbox_raw.decode() if isinstance(mbox_raw, bytes) else (mbox_raw or "")
        host = host_raw.decode() if isinstance(host_raw, bytes) else (host_raw or "")
        email_addr = f"{mailbox}@{host}" if mailbox and host else ""
        if name and email_addr:
            return f"{name} <{email_addr}>"
        return email_addr or name
    except Exception:
        return ""


def _decode_header(value: Any) -> str:
    """Decode an IMAP header value (bytes or encoded-word string)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if not isinstance(value, str):
        return str(value)
    # Decode RFC 2047 encoded words
    try:
        parts = email.header.decode_header(value)
        decoded = ""
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded += part.decode(charset or "utf-8", errors="replace")
            else:
                decoded += part
        return decoded
    except Exception:
        return value


def _parse_date(date_str: Any) -> datetime | None:
    """Parse IMAP ENVELOPE date string."""
    if not date_str:
        return None
    if isinstance(date_str, bytes):
        date_str = date_str.decode("utf-8", errors="replace")
    if not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M %z",
    ]
    # Strip comments like "(UTC)"
    date_str = re.sub(r"\s*\([^)]*\)", "", date_str).strip()
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    logger.debug("Could not parse date: %r", date_str)
    return None


def _parse_bodystructure(
    bs: Any, depth: int = 0
) -> tuple[bool, list[str]]:
    """
    Recursively parse IMAP BODYSTRUCTURE response.
    Returns (has_attachment, [filename, ...]).

    IMAP multipart BODYSTRUCTURE is a list/tuple where every element that is
    itself a list/tuple is a sub-part; the trailing string is the multipart
    subtype (e.g. "mixed").  We must walk ALL sibling parts, not just bs[0].
    """
    if bs is None or depth > 20:
        return False, []

    # Multipart: at least the first element is a nested part (list/tuple)
    if isinstance(bs, (list, tuple)) and bs and isinstance(bs[0], (list, tuple)):
        has_att = False
        names: list[str] = []
        for item in bs:
            if isinstance(item, (list, tuple)):
                sub_has, sub_names = _parse_bodystructure(item, depth + 1)
                has_att = has_att or sub_has
                names.extend(sub_names)
        return has_att, names

    # Single part
    try:
        main_type = _b(bs[0]).lower()
        sub_type = _b(bs[1]).lower()
        # bs[2] is params list (e.g. [b'NAME', b'file.pdf'])
        params = _params_dict(bs[2])
        # bs[5] is Content-ID, bs[6] is description, bs[7] is encoding, bs[8] is size
        # bs[9] for text is line count; check bs[9] for other as disposition
        disposition_info = bs[9] if len(bs) > 9 else None

        filename = params.get("name", "") or params.get("filename", "")
        if not filename and isinstance(disposition_info, (list, tuple)):
            disp_params = _params_dict(disposition_info[1] if len(disposition_info) > 1 else [])
            filename = disp_params.get("filename", "")

        is_attachment = False
        if isinstance(disposition_info, (list, tuple)) and disposition_info:
            disp = _b(disposition_info[0]).lower()
            if "attachment" in disp:
                is_attachment = True

        if not is_attachment and filename:
            if main_type in ("application", "image") and sub_type not in ("inline",):
                is_attachment = True

        if is_attachment and filename:
            return True, [filename]
        if is_attachment:
            return True, [f"{main_type}/{sub_type}"]
    except Exception as exc:
        logger.debug("Could not parse BODYSTRUCTURE part: %s", exc)

    return False, []


def _b(val: Any) -> str:
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


def _params_dict(params: Any) -> dict[str, str]:
    """Convert IMAP params list [key, val, key, val, ...] to dict."""
    result: dict[str, str] = {}
    if not isinstance(params, (list, tuple)):
        return result
    it = iter(params)
    try:
        while True:
            key = _b(next(it)).lower()
            val = _b(next(it))
            result[key] = val
    except StopIteration:
        pass
    return result
