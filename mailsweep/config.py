"""Application configuration — paths, defaults."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "MailSweep"
APP_VERSION = "0.1.0"

# ── Directories ───────────────────────────────────────────────────────────────

_XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

DATA_DIR: Path = _XDG_DATA / "mailsweep"
CONFIG_DIR: Path = _XDG_CONFIG / "mailsweep"
DB_PATH: Path = DATA_DIR / "mailsweep.db"
DEFAULT_SAVE_DIR: Path = Path.home() / "MailSweep_Attachments"
LOG_PATH: Path = DATA_DIR / "mailsweep.log"

for _d in (DATA_DIR, CONFIG_DIR, DEFAULT_SAVE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Scan settings ─────────────────────────────────────────────────────────────

SCAN_BATCH_SIZE: int = 500
SCAN_TIMEOUT_SECONDS: int = 60

# ── UI ────────────────────────────────────────────────────────────────────────

MESSAGE_TABLE_MAX_ROWS: int = 5000
TREEMAP_MIN_SIZE_BYTES: int = 1024  # Don't draw tiles smaller than 1 KB
