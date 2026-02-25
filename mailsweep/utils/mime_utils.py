"""MIME utilities — strip attachments from email messages safely."""
from __future__ import annotations

import email
import email.policy
import logging
import os
from datetime import datetime, timezone
from email.message import Message as EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

MAILSWEEP_HEADER = "X-MailSweep-Detached"


def strip_attachments(
    raw_bytes: bytes,
    save_dir: Path,
    uid: int,
) -> tuple[bytes, list[str]]:
    """
    Parse raw_bytes as an RFC 2822 message, save every attachment to save_dir,
    and return (cleaned_bytes, list_of_saved_filenames).

    Uses compat32 policy to preserve wire format for safe re-upload.
    """
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.compat32)
    saved: list[str] = []

    _walk_and_strip(msg, save_dir, uid, saved)

    # Add audit header
    timestamp = datetime.now(timezone.utc).isoformat()
    msg[MAILSWEEP_HEADER] = f"Detached {len(saved)} attachment(s) at {timestamp}"

    return msg.as_bytes(), saved


def _walk_and_strip(
    msg: EmailMessage,
    save_dir: Path,
    uid: int,
    saved: list[str],
    depth: int = 0,
) -> bool:
    """
    Recursively walk the MIME tree.
    Returns True if this part was removed (caller should drop it).
    """
    if depth > 20:
        logger.warning("MIME tree too deep at uid=%d depth=%d, stopping", uid, depth)
        return False

    content_type = msg.get_content_type()
    disposition = (msg.get("Content-Disposition") or "").lower()

    # Leaf part that is an attachment
    if not msg.is_multipart():
        if _is_attachment(msg):
            filename = _safe_filename(msg, uid, len(saved))
            dest = save_dir / filename
            size = _save_part(msg, dest)
            saved.append(filename)
            # Replace with placeholder pointing to saved file
            _replace_with_placeholder(msg, filename, dest, size)
            return False  # Keep the part (now a placeholder), don't remove
        return False

    # Multipart: recurse children in-place (they become placeholders)
    payload = msg.get_payload()
    if not isinstance(payload, list):
        return False

    for child in payload:
        if isinstance(child, EmailMessage):
            _walk_and_strip(child, save_dir, uid, saved, depth + 1)

    return False


def _is_attachment(part: EmailMessage) -> bool:
    """Return True if this part should be treated as an attachment."""
    disposition = (part.get("Content-Disposition") or "").lower()
    if "attachment" in disposition:
        return True
    # Also treat non-inline application/* and image/* as attachments
    # when they have a filename
    content_type = part.get_content_type()
    if part.get_filename() and content_type.startswith(("application/", "image/")):
        return True
    return False


def _save_part(part: EmailMessage, dest: Path) -> int:
    """Decode and save a MIME part to dest. Returns size in bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = part.get_payload(decode=True)
    if payload is None:
        logger.warning("Empty payload for part, skipping save to %s", dest)
        return 0
    dest.write_bytes(payload)
    logger.info("Saved attachment: %s (%d bytes)", dest, len(payload))
    return len(payload)


def _replace_with_placeholder(
    part: EmailMessage, original_name: str, local_path: Path, size: int
) -> None:
    """Replace an attachment part's content with a text placeholder
    that records the original filename, size, and local save path."""
    from mailsweep.utils.size_fmt import human_size

    placeholder = (
        f"[Attachment detached by MailSweep]\n"
        f"Original file: {original_name}\n"
        f"Size: {human_size(size)}\n"
        f"Saved to: {local_path}\n"
    )

    # Clear existing content headers
    for hdr in ("Content-Transfer-Encoding", "Content-Disposition"):
        if hdr in part:
            del part[hdr]

    # Replace Content-Type and payload
    del part["Content-Type"]
    part["Content-Type"] = f'text/plain; charset="utf-8"; name="{original_name}.txt"'
    part["Content-Disposition"] = f'inline; filename="{original_name}.txt"'
    part.set_payload(placeholder, charset="utf-8")


def _safe_filename(part: EmailMessage, uid: int, idx: int) -> str:
    """Derive a safe filesystem filename from the MIME part."""
    raw = part.get_filename() or f"attachment_{uid}_{idx}"
    # Decode encoded-word filenames
    from email.header import decode_header
    decoded_parts = decode_header(raw)
    filename = ""
    for part_bytes, charset in decoded_parts:
        if isinstance(part_bytes, bytes):
            filename += part_bytes.decode(charset or "utf-8", errors="replace")
        else:
            filename += part_bytes

    # Strip path traversal
    filename = os.path.basename(filename.replace("\\", "/"))
    # Remove null bytes and other dangerous chars
    filename = "".join(c for c in filename if c.isprintable() and c not in "/\\:*?\"<>|")
    filename = filename.strip(". ") or f"attachment_{uid}_{idx}"

    # Ensure unique by prepending uid
    return f"{uid}_{idx}_{filename}"


def _unwrap_single_child(parent: EmailMessage, child: EmailMessage) -> None:
    """
    Copy child's headers and payload into parent, effectively unwrapping
    the degenerate multipart/mixed with a single part.
    """
    # Copy content-relevant headers from child
    for key in ("Content-Type", "Content-Transfer-Encoding", "Content-Disposition"):
        if key in parent:
            del parent[key]
        if child[key]:
            parent[key] = child[key]

    parent.set_payload(child.get_payload())


def get_attachment_info(raw_bytes: bytes) -> tuple[bool, list[str]]:
    """
    Quick scan of BODYSTRUCTURE-equivalent using python email parser.
    Returns (has_attachment, [filename, ...]).
    Used as fallback when BODYSTRUCTURE IMAP response is unavailable.
    """
    try:
        msg = email.message_from_bytes(raw_bytes, policy=email.policy.compat32)
        names: list[str] = []
        for part in msg.walk():
            if _is_attachment(part):
                fn = part.get_filename() or "unnamed"
                names.append(fn)
        return bool(names), names
    except Exception as exc:
        logger.warning("get_attachment_info failed: %s", exc)
        return False, []
