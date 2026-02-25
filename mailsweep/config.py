"""Application configuration — paths, defaults, persistence."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

APP_NAME = "MailSweep"
APP_VERSION = "0.3.2"

logger = logging.getLogger(__name__)

# ── Directories ───────────────────────────────────────────────────────────────

_XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

DATA_DIR: Path = _XDG_DATA / "mailsweep"
CONFIG_DIR: Path = _XDG_CONFIG / "mailsweep"
DB_PATH: Path = DATA_DIR / "mailsweep.db"
DEFAULT_SAVE_DIR: Path = Path.home() / "MailSweep_Attachments"
LOG_PATH: Path = DATA_DIR / "mailsweep.log"
SETTINGS_PATH: Path = CONFIG_DIR / "settings.json"

for _d in (DATA_DIR, CONFIG_DIR, DEFAULT_SAVE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Scan settings ─────────────────────────────────────────────────────────────

SCAN_BATCH_SIZE: int = 500
SCAN_TIMEOUT_SECONDS: int = 60

# ── UI ────────────────────────────────────────────────────────────────────────

MESSAGE_TABLE_MAX_ROWS: int = 5000
TREEMAP_MIN_SIZE_BYTES: int = 1024  # Don't draw tiles smaller than 1 KB

# ── AI ───────────────────────────────────────────────────────────────────────

UNLABELLED_MODE: str = "no_thread"       # no_thread | in_reply_to | gmail_thread

AI_PROVIDER: str = "ollama"              # ollama | openai | anthropic | custom
AI_BASE_URL: str = "http://localhost:11434/v1"
AI_API_KEY: str = ""
AI_MODEL: str = "llama3.2"


# ── Persistence ───────────────────────────────────────────────────────────────

def save_settings() -> None:
    """Persist user-changeable settings to disk.  AI API key goes to keyring."""
    data = {
        "scan_batch_size": SCAN_BATCH_SIZE,
        "message_table_max_rows": MESSAGE_TABLE_MAX_ROWS,
        "default_save_dir": str(DEFAULT_SAVE_DIR),
        "unlabelled_mode": UNLABELLED_MODE,
        "ai_provider": AI_PROVIDER,
        "ai_base_url": AI_BASE_URL,
        "ai_model": AI_MODEL,
        # API key stored in keyring, not here
    }
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save settings: %s", exc)

    # Store AI API key in system keyring
    if AI_API_KEY:
        try:
            from mailsweep.utils.keyring_store import set_password
            set_password("ai_api_key", "mailsweep_ai", AI_API_KEY)
        except Exception as exc:
            logger.warning("Could not save AI API key to keyring: %s", exc)


def load_settings() -> None:
    """Load persisted settings from disk, falling back to defaults."""
    global SCAN_BATCH_SIZE, MESSAGE_TABLE_MAX_ROWS, DEFAULT_SAVE_DIR
    global UNLABELLED_MODE
    global AI_PROVIDER, AI_BASE_URL, AI_API_KEY, AI_MODEL
    if not SETTINGS_PATH.exists():
        return
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        SCAN_BATCH_SIZE = int(data.get("scan_batch_size", SCAN_BATCH_SIZE))
        MESSAGE_TABLE_MAX_ROWS = int(data.get("message_table_max_rows", MESSAGE_TABLE_MAX_ROWS))
        saved_dir = data.get("default_save_dir")
        if saved_dir:
            DEFAULT_SAVE_DIR = Path(saved_dir)
            DEFAULT_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        saved_mode = data.get("unlabelled_mode", UNLABELLED_MODE)
        if saved_mode in ("no_thread", "in_reply_to", "gmail_thread"):
            UNLABELLED_MODE = saved_mode
        AI_PROVIDER = data.get("ai_provider", AI_PROVIDER)
        AI_BASE_URL = data.get("ai_base_url", AI_BASE_URL)
        AI_MODEL = data.get("ai_model", AI_MODEL)
    except Exception as exc:
        logger.warning("Could not load settings: %s", exc)

    # Load AI API key from keyring
    try:
        from mailsweep.utils.keyring_store import get_password
        key = get_password("ai_api_key", "mailsweep_ai")
        if key:
            AI_API_KEY = key
    except Exception as exc:
        logger.debug("Could not load AI API key from keyring: %s", exc)


# Load on import so settings are available immediately
load_settings()
