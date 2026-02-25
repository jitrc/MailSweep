"""Account dataclass — represents an IMAP account configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AuthType(str, Enum):
    PASSWORD = "password"
    OAUTH2_GMAIL = "oauth2_gmail"
    OAUTH2_OUTLOOK = "oauth2_outlook"


@dataclass
class Account:
    id: int | None = None
    display_name: str = ""
    host: str = ""
    port: int = 993
    username: str = ""
    auth_type: AuthType = AuthType.PASSWORD
    use_ssl: bool = True

    def __str__(self) -> str:
        return f"{self.display_name} <{self.username}@{self.host}>"
