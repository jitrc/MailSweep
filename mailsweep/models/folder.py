"""Folder dataclass — represents an IMAP folder/mailbox."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Folder:
    id: int | None = None
    account_id: int = 0
    name: str = ""
    uid_validity: int = 0
    message_count: int = 0
    total_size_bytes: int = 0
    last_scanned_at: datetime | None = None

    @property
    def display_name(self) -> str:
        """Return the last component of the folder path for display."""
        return self.name.split("/")[-1] if "/" in self.name else self.name
