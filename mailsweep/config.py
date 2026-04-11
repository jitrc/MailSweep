"""Application configuration — paths, defaults, persistence."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

APP_NAME = "MailSweep"
APP_VERSION = "0.5.9"

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
COMMUNITY_BLOCKLIST_PATH: Path = CONFIG_DIR / "community_blocklist.txt"

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
SKIP_ALL_MAIL: bool = False              # Exclude [Gmail]/All Mail from sync, counts, filters, viz
BLOCKLIST_AUTO_MOVE: bool = False        # Move blocked emails automatically after scan (no prompt)
BLOCKLIST_USE_COMMUNITY: bool = False    # Include community blocklist from GitHub when checking
BLOCKLIST_COMMUNITY_URL: str = "https://raw.githubusercontent.com/dchau360/MailSweep-Blocklist/main/blocklist.txt"

AI_PROVIDER: str = "ollama"              # ollama | openai | anthropic | custom
AI_BASE_URL: str = "http://localhost:11434/v1"
AI_API_KEY: str = ""                     # key for the currently active provider
AI_API_KEYS: dict[str, str] = {}        # per-provider keys, keyed by provider name
AI_MODEL: str = "llama3.2"


# ── Persistence ───────────────────────────────────────────────────────────────

def save_settings() -> None:
    """Persist user-changeable settings to disk.  AI API key goes to keyring."""
    data = {
        "scan_batch_size": SCAN_BATCH_SIZE,
        "message_table_max_rows": MESSAGE_TABLE_MAX_ROWS,
        "default_save_dir": str(DEFAULT_SAVE_DIR),
        "unlabelled_mode": UNLABELLED_MODE,
        "skip_all_mail": SKIP_ALL_MAIL,
        "blocklist_auto_move": BLOCKLIST_AUTO_MOVE,
        "blocklist_use_community": BLOCKLIST_USE_COMMUNITY,
        "blocklist_community_url": BLOCKLIST_COMMUNITY_URL,
        "ai_provider": AI_PROVIDER,
        "ai_base_url": AI_BASE_URL,
        "ai_model": AI_MODEL,
        # API key stored in keyring, not here
    }
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save settings: %s", exc)

    # Store AI API keys in system keyring (one entry per provider)
    try:
        from mailsweep.utils.keyring_store import set_password
        for _provider, _key in AI_API_KEYS.items():
            set_password("ai_api_key", f"mailsweep_ai_{_provider}", _key)
        # Legacy single-key entry kept for backwards compat
        if AI_API_KEY:
            set_password("ai_api_key", "mailsweep_ai", AI_API_KEY)
    except Exception as exc:
        logger.warning("Could not save AI API key to keyring: %s", exc)


def load_settings() -> None:
    """Load persisted settings from disk, falling back to defaults."""
    global SCAN_BATCH_SIZE, MESSAGE_TABLE_MAX_ROWS, DEFAULT_SAVE_DIR
    global UNLABELLED_MODE, SKIP_ALL_MAIL, BLOCKLIST_AUTO_MOVE, BLOCKLIST_USE_COMMUNITY, BLOCKLIST_COMMUNITY_URL
    global AI_PROVIDER, AI_BASE_URL, AI_API_KEY, AI_API_KEYS, AI_MODEL
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
        SKIP_ALL_MAIL = bool(data.get("skip_all_mail", SKIP_ALL_MAIL))
        BLOCKLIST_AUTO_MOVE = bool(data.get("blocklist_auto_move", BLOCKLIST_AUTO_MOVE))
        BLOCKLIST_USE_COMMUNITY = bool(data.get("blocklist_use_community", BLOCKLIST_USE_COMMUNITY))
        BLOCKLIST_COMMUNITY_URL = data.get("blocklist_community_url", BLOCKLIST_COMMUNITY_URL)
        AI_PROVIDER = data.get("ai_provider", AI_PROVIDER)
        AI_BASE_URL = data.get("ai_base_url", AI_BASE_URL)
        AI_MODEL = data.get("ai_model", AI_MODEL)
    except Exception as exc:
        logger.warning("Could not load settings: %s", exc)

    # Load AI API keys from keyring (per-provider entries)
    try:
        from mailsweep.utils.keyring_store import get_password
        for _provider in ("ollama", "lm-studio", "openai", "anthropic", "custom"):
            _key = get_password("ai_api_key", f"mailsweep_ai_{_provider}")
            if _key:
                AI_API_KEYS[_provider] = _key
        # Legacy fallback: single key entry
        if not AI_API_KEYS.get(AI_PROVIDER):
            _key = get_password("ai_api_key", "mailsweep_ai")
            if _key:
                AI_API_KEYS[AI_PROVIDER] = _key
        AI_API_KEY = AI_API_KEYS.get(AI_PROVIDER, "")
    except Exception as exc:
        logger.debug("Could not load AI API key from keyring: %s", exc)


def load_community_patterns() -> set[str]:
    """Load community blocklist patterns from the local cache file.

    Returns an empty set if the file doesn't exist or community list is disabled.
    """
    if not BLOCKLIST_USE_COMMUNITY:
        return set()
    if not COMMUNITY_BLOCKLIST_PATH.exists():
        return set()
    try:
        lines = COMMUNITY_BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines()
        return {l.strip().lower() for l in lines if l.strip() and not l.strip().startswith("#")}
    except Exception as exc:
        logger.warning("Could not load community blocklist: %s", exc)
        return set()


# Load on import so settings are available immediately
load_settings()
