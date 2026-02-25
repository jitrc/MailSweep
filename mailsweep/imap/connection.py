"""IMAP connection factory — password auth and OAuth2."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from imapclient import IMAPClient

from mailsweep.models.account import Account, AuthType
from mailsweep.utils.keyring_store import get_password, get_token

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class IMAPConnectionError(Exception):
    pass


def connect(account: Account, timeout: int = 30) -> IMAPClient:
    """
    Create and authenticate an IMAPClient for the given account.
    Raises IMAPConnectionError on failure.
    """
    try:
        client = IMAPClient(
            host=account.host,
            port=account.port,
            ssl=account.use_ssl,
            timeout=timeout,
        )
    except Exception as exc:
        raise IMAPConnectionError(f"Cannot connect to {account.host}:{account.port}: {exc}") from exc

    try:
        if account.auth_type == AuthType.PASSWORD:
            _auth_password(client, account)
        elif account.auth_type == AuthType.OAUTH2_GMAIL:
            _auth_oauth2_gmail(client, account)
        elif account.auth_type == AuthType.OAUTH2_OUTLOOK:
            _auth_oauth2_outlook(client, account)
        else:
            raise IMAPConnectionError(f"Unknown auth_type: {account.auth_type}")
    except IMAPConnectionError:
        raise
    except Exception as exc:
        raise IMAPConnectionError(f"Authentication failed for {account.username}: {exc}") from exc

    return client


def _auth_password(client: IMAPClient, account: Account) -> None:
    password = get_password(account.username, account.host)
    if password is None:
        raise IMAPConnectionError(
            f"No password found for {account.username}@{account.host}. "
            "Please add the account again to set credentials."
        )
    client.login(account.username, password)
    logger.info("Authenticated %s@%s via password", account.username, account.host)


def _auth_oauth2_gmail(client: IMAPClient, account: Account) -> None:
    from mailsweep.imap.oauth2 import get_gmail_access_token

    access_token = get_gmail_access_token(account.username)
    if not access_token:
        raise IMAPConnectionError(
            f"No Gmail OAuth2 token for {account.username}. "
            "Please re-authorize via Account Settings."
        )
    auth_string = f"user={account.username}\x01auth=Bearer {access_token}\x01\x01"
    client.authenticate("XOAUTH2", lambda x: auth_string)
    logger.info("Authenticated %s via Gmail XOAUTH2", account.username)


def _auth_oauth2_outlook(client: IMAPClient, account: Account) -> None:
    from mailsweep.imap.oauth2 import get_outlook_access_token

    access_token = get_outlook_access_token(account.username)
    if not access_token:
        raise IMAPConnectionError(
            f"No Outlook OAuth2 token for {account.username}. "
            "Please re-authorize via Account Settings."
        )
    auth_string = f"user={account.username}\x01auth=Bearer {access_token}\x01\x01"
    client.authenticate("XOAUTH2", lambda x: auth_string)
    logger.info("Authenticated %s via Outlook XOAUTH2", account.username)


def list_folders(client: IMAPClient) -> list[str]:
    """Return a flat list of all folder names on the server."""
    folders = []
    for flags, delimiter, name in client.list_folders():
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        folders.append(name)
    return sorted(folders)
