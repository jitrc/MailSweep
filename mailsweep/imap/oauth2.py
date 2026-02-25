"""OAuth2 helpers for Gmail (XOAUTH2) and Outlook (MSAL)."""
from __future__ import annotations

import json
import logging
from typing import Any

from mailsweep.utils.keyring_store import get_token, set_token

logger = logging.getLogger(__name__)

# ── Gmail ─────────────────────────────────────────────────────────────────────

GMAIL_SCOPES = [
    "https://mail.google.com/",
]

GMAIL_TOKEN_KEY_PREFIX = "gmail"


def authorize_gmail(username: str, client_id: str, client_secret: str) -> str | None:
    """
    Run the Google OAuth2 installed-app desktop flow.
    Opens the browser for consent; returns the access token on success.
    Stores credentials in keyring for future sessions.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)

        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or GMAIL_SCOPES),
        }
        set_token(f"{GMAIL_TOKEN_KEY_PREFIX}:{username}", json.dumps(token_data))
        return creds.token

    except Exception as exc:
        logger.error("Gmail authorization failed: %s", exc)
        return None


def get_gmail_access_token(username: str) -> str | None:
    """Return a valid Gmail access token, refreshing if needed."""
    try:
        import google.auth.transport.requests
        from google.oauth2.credentials import Credentials

        raw = get_token(f"{GMAIL_TOKEN_KEY_PREFIX}:{username}")
        if not raw:
            return None

        data: dict[str, Any] = json.loads(raw)
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes", GMAIL_SCOPES),
        )

        if creds.expired and creds.refresh_token:
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            # Persist refreshed token
            data["token"] = creds.token
            set_token(f"{GMAIL_TOKEN_KEY_PREFIX}:{username}", json.dumps(data))

        return creds.token

    except Exception as exc:
        logger.warning("get_gmail_access_token failed: %s", exc)
        return None


# ── Outlook / Microsoft ────────────────────────────────────────────────────────

OUTLOOK_AUTHORITY = "https://login.microsoftonline.com/common"
OUTLOOK_SCOPES = ["https://outlook.office365.com/IMAP.AccessAsUser.All", "offline_access"]
OUTLOOK_TOKEN_KEY_PREFIX = "outlook"


def authorize_outlook(username: str, client_id: str) -> str | None:
    """
    Run the MSAL interactive desktop flow for Outlook/Office365.
    Returns the access token on success.
    """
    try:
        import msal

        app = msal.PublicClientApplication(client_id, authority=OUTLOOK_AUTHORITY)
        result = app.acquire_token_interactive(scopes=OUTLOOK_SCOPES, login_hint=username)

        if "error" in result:
            logger.error("MSAL error: %s — %s", result["error"], result.get("error_description"))
            return None

        token_data = {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token"),
            "client_id": client_id,
        }
        set_token(f"{OUTLOOK_TOKEN_KEY_PREFIX}:{username}", json.dumps(token_data))
        return result["access_token"]

    except Exception as exc:
        logger.error("Outlook authorization failed: %s", exc)
        return None


def get_outlook_access_token(username: str) -> str | None:
    """Return a valid Outlook access token, refreshing via MSAL cache if possible."""
    try:
        import msal

        raw = get_token(f"{OUTLOOK_TOKEN_KEY_PREFIX}:{username}")
        if not raw:
            return None

        data: dict[str, Any] = json.loads(raw)
        client_id = data.get("client_id", "")
        refresh_token = data.get("refresh_token")

        if not refresh_token:
            return data.get("access_token")

        app = msal.PublicClientApplication(client_id, authority=OUTLOOK_AUTHORITY)
        result = app.acquire_token_by_refresh_token(refresh_token, scopes=OUTLOOK_SCOPES)

        if "error" in result:
            logger.warning("MSAL refresh failed: %s — %s",
                           result.get("error"), result.get("error_description"))
            return None

        data["access_token"] = result["access_token"]
        if "refresh_token" in result:
            data["refresh_token"] = result["refresh_token"]
        set_token(f"{OUTLOOK_TOKEN_KEY_PREFIX}:{username}", json.dumps(data))
        return result["access_token"]

    except Exception as exc:
        logger.warning("get_outlook_access_token failed: %s", exc)
        return None
