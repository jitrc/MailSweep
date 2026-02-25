"""Application configuration — paths, defaults, persistence."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

APP_NAME = "MailSweep"
APP_VERSION = "0.1.0"

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


# ── Persistence ───────────────────────────────────────────────────────────────

def save_settings() -> None:
    """Persist user-changeable settings to disk."""
    data = {
        "scan_batch_size": SCAN_BATCH_SIZE,
        "message_table_max_rows": MESSAGE_TABLE_MAX_ROWS,
        "default_save_dir": str(DEFAULT_SAVE_DIR),
    }
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save settings: %s", exc)


def load_settings() -> None:
    """Load persisted settings from disk, falling back to defaults."""
    global SCAN_BATCH_SIZE, MESSAGE_TABLE_MAX_ROWS, DEFAULT_SAVE_DIR
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
    except Exception as exc:
        logger.warning("Could not load settings: %s", exc)


# Load on import so settings are available immediately
load_settings()
