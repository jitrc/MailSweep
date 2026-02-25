"""Message dataclass — represents an IMAP message (metadata only, no body)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Message:
    id: int | None = None
    uid: int = 0
    folder_id: int = 0
    from_addr: str = ""
    subject: str = ""
    date: datetime | None = None
    size_bytes: int = 0
    has_attachment: bool = False
    attachment_names: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    cached_at: datetime | None = None

    # Transient field for display — populated by joins
    folder_name: str = ""

    @property
    def attachment_names_json(self) -> str:
        return json.dumps(self.attachment_names)

    @property
    def flags_json(self) -> str:
        return json.dumps(self.flags)

    @classmethod
    def from_row(cls, row: dict) -> "Message":
        return cls(
            id=row["id"],
            uid=row["uid"],
            folder_id=row["folder_id"],
            from_addr=row["from_addr"] or "",
            subject=row["subject"] or "",
            date=datetime.fromisoformat(row["date"]) if row.get("date") else None,
            size_bytes=row["size_bytes"] or 0,
            has_attachment=bool(row["has_attachment"]),
            attachment_names=json.loads(row["attachment_names"] or "[]"),
            flags=json.loads(row["flags"] or "[]"),
            cached_at=datetime.fromisoformat(row["cached_at"]) if row.get("cached_at") else None,
            folder_name=row.get("folder_name", ""),
        )
