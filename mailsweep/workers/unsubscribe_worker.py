"""UnsubscribeWorker — fetches List-Unsubscribe headers and processes them.

Strategy per message:
  - If List-Unsubscribe-Post: List-Unsubscribe=One-Click AND an https URL exists
    → silent HTTP POST (RFC 8058 one-click), no browser needed.
  - If only an https URL exists
    → emit need_webview so the UI can open a sandboxed browser.
  - If only mailto exists
    → skip (no SMTP support yet).
  - If no header
    → skip.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from collections import defaultdict
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, pyqtSignal

from mailsweep.imap.connection import IMAPConnectionError, connect
from mailsweep.models.account import Account
from mailsweep.models.message import Message

logger = logging.getLogger(__name__)

_UNSUB_FETCH = [b"BODY[HEADER.FIELDS (LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)]"]


class UnsubscribeWorker(QObject):
    progress = pyqtSignal(int, int, str)   # done, total, status_msg
    message_done = pyqtSignal(object, str) # Message, status
    need_webview = pyqtSignal(str, str)    # url, from_addr
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        account: Account,
        messages: list[Message],
        folder_id_to_name: dict[int, str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._messages = messages
        self._folder_id_to_name = folder_id_to_name
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            client = connect(self._account)
        except IMAPConnectionError as exc:
            self.error.emit(f"Connection failed: {exc}")
            self.finished.emit()
            return

        total = len(self._messages)
        done = 0
        seen_urls: set[str] = set()  # deduplicate across all folders

        by_folder: dict[int, list[Message]] = defaultdict(list)
        for msg in self._messages:
            by_folder[msg.folder_id].append(msg)

        try:
            for folder_id, folder_msgs in by_folder.items():
                if self._cancel_requested:
                    break

                folder_name = self._folder_id_to_name.get(folder_id, str(folder_id))
                try:
                    client.select_folder(folder_name, readonly=True)
                except Exception as exc:
                    err_lower = str(exc).lower()
                    status = "no_header" if ("does not exist" in err_lower or "trycreate" in err_lower) else "error"
                    logger.warning("Cannot select %s: %s", folder_name, exc)
                    for msg in folder_msgs:
                        self.message_done.emit(msg, status)
                        done += 1
                    continue

                uid_to_msg = {msg.uid: msg for msg in folder_msgs}
                try:
                    fetch_data = client.fetch(list(uid_to_msg.keys()), _UNSUB_FETCH)
                except Exception as exc:
                    logger.error("Header fetch failed for %s: %s", folder_name, exc)
                    for msg in folder_msgs:
                        self.message_done.emit(msg, "error")
                        done += 1
                    continue

                # seen_urls is shared across folders — one request per unique URL total.
                for uid, data in fetch_data.items():
                    msg = uid_to_msg.get(uid)
                    if not msg:
                        continue

                    self.progress.emit(done, total, f"Processing {msg.from_addr[:50]}…")

                    raw = b""
                    for key, val in data.items():
                        if isinstance(key, bytes) and key.lower().startswith(b"body["):
                            raw = val if isinstance(val, bytes) else str(val).encode()
                            break

                    unsub_url, is_one_click = _parse_unsub_headers(raw)

                    if not unsub_url:
                        self.message_done.emit(msg, "no_header")
                    elif unsub_url in seen_urls:
                        self.message_done.emit(msg, "duplicate_skipped")
                    elif is_one_click:
                        seen_urls.add(unsub_url)
                        status = _do_one_click_post(unsub_url)
                        self.message_done.emit(msg, status)
                    else:
                        seen_urls.add(unsub_url)
                        self.need_webview.emit(unsub_url, msg.from_addr)
                        self.message_done.emit(msg, "needs_browser")

                    done += 1
                    self.progress.emit(done, total, f"Done {done}/{total}")

        finally:
            try:
                client.logout()
            except Exception:
                pass
            self.finished.emit()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_unsub_headers(raw: bytes) -> tuple[str, bool]:
    """Return (https_url, is_one_click) from raw List-Unsubscribe header bytes."""
    text = raw.decode("utf-8", errors="replace")
    unsub_value = ""
    is_one_click = False

    for line in text.splitlines():
        low = line.lower()
        if low.startswith("list-unsubscribe:"):
            unsub_value = line[len("list-unsubscribe:"):].strip()
        elif low.startswith("list-unsubscribe-post:"):
            val = line[len("list-unsubscribe-post:"):].strip()
            if "List-Unsubscribe=One-Click" in val:
                is_one_click = True

    https_url = _extract_https_url(unsub_value)
    return https_url, is_one_click


def _extract_https_url(header_value: str) -> str:
    """Extract the first https:// URL from a List-Unsubscribe header value."""
    matches = re.findall(r"<(https://[^>]+)>", header_value)
    return matches[0] if matches else ""


def _do_one_click_post(url: str) -> str:
    """Perform RFC 8058 one-click unsubscribe POST. Returns a status string."""
    try:
        req = urllib.request.Request(
            url,
            data=b"List-Unsubscribe=One-Click",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("One-click unsubscribe POST %s → %d", url, resp.status)
            return "one_click_ok"
    except Exception as exc:
        logger.warning("One-click POST failed for %s: %s", url, exc)
        return "one_click_failed"
