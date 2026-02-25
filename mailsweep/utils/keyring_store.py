"""Credential storage via system keyring (Secret Service / macOS Keychain / Windows Credential Manager)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "MailSweep"


def set_password(username: str, host: str, password: str) -> bool:
    """Store password in system keyring. Returns True on success."""
    try:
        import keyring
        keyring.set_password(f"{SERVICE_NAME}:{host}", username, password)
        return True
    except Exception as exc:
        logger.warning("keyring set failed: %s", exc)
        return False


def get_password(username: str, host: str) -> str | None:
    """Retrieve password from system keyring. Returns None if not found."""
    try:
        import keyring
        return keyring.get_password(f"{SERVICE_NAME}:{host}", username)
    except Exception as exc:
        logger.warning("keyring get failed: %s", exc)
        return None


def delete_password(username: str, host: str) -> bool:
    """Remove password from system keyring. Returns True on success."""
    try:
        import keyring
        keyring.delete_password(f"{SERVICE_NAME}:{host}", username)
        return True
    except Exception as exc:
        logger.warning("keyring delete failed: %s", exc)
        return False


def set_token(key: str, token_json: str) -> bool:
    """Store an OAuth2 token JSON blob under key."""
    try:
        import keyring
        keyring.set_password(SERVICE_NAME, f"oauth2:{key}", token_json)
        return True
    except Exception as exc:
        logger.warning("keyring token set failed: %s", exc)
        return False


def get_token(key: str) -> str | None:
    """Retrieve an OAuth2 token JSON blob by key."""
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, f"oauth2:{key}")
    except Exception as exc:
        logger.warning("keyring token get failed: %s", exc)
        return None
