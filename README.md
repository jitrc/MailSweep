# MailSweep

**IMAP Mailbox Analyzer & Cleaner** — like WinDirStat/Baobab for your email.

Visualize where your email storage is going, then surgically reclaim it with
bulk attachment extraction, detach, backup, and delete operations.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Screenshots

### Treemap Views

| Folders | Senders | Messages |
|---------|---------|----------|
| ![Folders](images/Viz_folders.png) | ![Senders](images/viz_senders.png) | ![Messages](images/viz_messages.png) |

### Unlabelled Messages

| By Sender | By Message |
|-----------|------------|
| ![Unlabelled Senders](images/unlabellled_senders.png) | ![Unlabelled Messages](images/unlabellled_messages.png) |

### AI Assistant & Settings

| AI Suggestions | Account Settings | Settings |
|----------------|------------------|----------|
| ![AI Suggestions](images/AI_Suggestions.png) | ![Account Settings](images/account_settings.png) | ![Settings](images/settings.png) |

## Features

- **Treemap visualization** — see which folders, senders, or messages consume the most space
- **Folder drill-down** — click into sub-labels, explore messages inside any folder
- **Bulk attachment extraction** — save attachments locally without modifying server messages
- **Attachment detach** — strip attachments from server messages, replace with placeholder text showing local file path
- **Backup to .eml** — download full messages as RFC822 files
- **Backup & delete** — backup then safely remove from server (Gmail-safe: copies to Trash first)
- **Smart size display** — deduplicates Gmail labels so total size reflects actual storage usage
- **IMAP quota** — shows server-reported storage usage and limit
- **Incremental scan** — rescan only fetches new/changed messages using UIDVALIDITY
- **OAuth2 support** — Gmail (XOAUTH2) and Outlook (MSAL), plus password/app-password auth
- **Filter bar** — filter by sender, subject, date range, size range, attachment presence
- **AI assistant** — LLM-powered mailbox analysis (Ollama, LM Studio, OpenAI, Anthropic) with dynamic model dropdowns and Refresh to discover local models; find misfilings, dead folders, sender overlap; apply AI-suggested IMAP moves with one click

## Installation

```bash
# Clone and install
git clone https://github.com/jitrc/MailSweep.git
cd mailsweep
uv sync --dev

# Run the GUI
uv run mailsweep

# Run the CLI (prints folder sizes, no GUI)
uv run mailsweep-cli --host imap.gmail.com --username you@gmail.com
```

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager (recommended) or pip

## Quick Start

1. Launch: `uv run mailsweep`
2. Click **Add Account** and enter your IMAP server details
3. Click **Scan Mailbox** to fetch message metadata (no message bodies downloaded)
4. Browse the treemap, filter bar, and folder tree to explore your mailbox
5. Select messages and use the toolbar or right-click menu for operations

### Gmail Setup

**Recommended:** Use **Auth Type: Password** with a
[Gmail App Password](https://myaccount.google.com/apppasswords)
(requires 2-Step Verification). No cloud project needed.

**OAuth2 alternative:** Create credentials in
[Google Cloud Console](https://console.cloud.google.com/) >
APIs & Services > Credentials > OAuth 2.0 Client ID (Desktop app type).

### Other Providers

| Provider | Host | Port | Auth |
|----------|------|------|------|
| Gmail | imap.gmail.com | 993 | App Password or OAuth2 |
| Outlook | outlook.office365.com | 993 | Password or OAuth2 |
| Yahoo | imap.mail.yahoo.com | 993 | App Password |
| ProtonMail | 127.0.0.1 | 1143 | Bridge password |
| Fastmail | imap.fastmail.com | 993 | App Password |

## Operations

| Operation | Server Modified? | Description |
|-----------|-------------------|-------------|
| **Extract Attachments** | No | Save attachments to local disk |
| **Detach Attachments** | Yes | Save locally + replace attachment in message with placeholder |
| **Backup** | No | Download full message as .eml file |
| **Backup & Delete** | Yes | Download .eml then move message to Trash |
| **Delete** | Yes | Move message to Trash (Gmail-safe) |
| **AI Move** | Yes | LLM suggests moves → user confirms → messages moved via IMAP |

## Data Locations

| Item | Path |
|------|------|
| SQLite cache | `~/.local/share/mailsweep/mailsweep.db` |
| Settings | `~/.config/mailsweep/settings.json` |
| Saved attachments | `~/MailSweep_Attachments/` |
| Backup .eml files | `~/MailSweep_Attachments/backups/` |
| App log | `~/.local/share/mailsweep/mailsweep.log` |

All paths follow XDG Base Directory conventions. The save directory can be
changed in Settings.

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check mailsweep/

# Type check
uv run mypy mailsweep/
```

## How It Works

- **Scan** uses `FETCH [ENVELOPE, RFC822.SIZE, BODYSTRUCTURE]` — gets sender, subject, date,
  size, and full MIME tree without downloading any message bodies. Batched in groups of 500 UIDs.
- **Incremental rescan** checks `UIDVALIDITY`, then diffs server UIDs vs cache to fetch only new messages.
- **Attachment detach** parses the full RFC822 message with Python's `email` library (compat32 policy
  for safe re-upload), replaces attachment parts with text/plain placeholders, then APPENDs the
  cleaned message back to the same folder and expunges the original.
- **Gmail-safe delete** copies messages to `[Gmail]/Trash` before expunging, preventing permanent
  deletion on Gmail where `\Deleted` + `EXPUNGE` on `[Gmail]/All Mail` bypasses Trash entirely.
- **Credentials** are stored in the system keychain via the `keyring` library (Secret Service on
  Linux, Keychain on macOS, Credential Manager on Windows). Never stored in files or logged.
- **AI assistant** uses stdlib `urllib.request` to call LLM APIs (zero new dependencies). Builds a
  markdown context from the SQLite cache (folder tree, top senders, cross-folder overlap, dead folders)
  and sends it as system prompt. Supports Ollama, LM Studio (local), OpenAI, and Anthropic.
  Model dropdowns are pre-populated per provider; a Refresh button discovers models from local
  servers via the `/v1/models` endpoint. IMAP moves use RFC 6851 `MOVE` with
  `COPY`+`DELETE`+`EXPUNGE` fallback.

## Author

Jit Ray Chowdhury

## License

MIT
