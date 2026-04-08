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
- **OAuth2 support** — Gmail (XOAUTH2) and Outlook (MSAL); Outlook OAuth2 requires a Microsoft 365 developer account or a work/school Azure tenant
- **Filter bar** — filter by sender, subject, date range, size range, attachment presence
- **AI assistant** — LLM-powered mailbox analysis (Ollama, LM Studio, OpenAI, Anthropic) with dynamic model dropdowns and Refresh to discover local models; find misfilings, dead folders, sender overlap; apply AI-suggested IMAP moves with one click
- **Bulk unsubscribe** — right-click selected messages to unsubscribe from mailing lists; supports RFC 8058 one-click unsubscribe (silent POST) and sandboxed browser for manual confirmation pages
- **Unsubscribe & Delete** — unsubscribe and move to Trash in one action; deduplicates requests so each unique unsubscribe URL is only called once even when multiple messages from the same sender are selected
- **Select-all checkbox** — checkbox in the message table header selects or deselects all visible messages; shows tri-state (partial) indicator when only some rows are checked
- **Fast batch delete** — bulk delete sends messages to Trash in optimised batches with automatic rate-limit retry; significantly faster than deleting one message at a time
- **Provider profiles** — Add Account dialog includes preset profiles for Gmail, Outlook, Yahoo, ProtonMail, and Fastmail that auto-fill host, port, SSL, and auth type
- **Senders sidebar** — inline sender list in the left panel; click a sender to filter the message table to only their messages; right-click for the full sender action menu
- **Sender List** — browse all unique senders sorted by message count or size; status bar shows total size across all senders; multi-select and right-click to delete, block and delete, backup and delete, permanent delete, or block and permanent delete in one action
- **Permanent Delete** — right-click any message selection to permanently expunge without moving to Trash first; also available per-sender from the Sender List, Senders sidebar, and the message table context menu (includes Permanent Delete All From Sender and Block && Permanent Delete All From Sender)
- **Empty Trash** — Actions → Empty Trash… permanently expunges all messages in the Trash folder in one step
- **Sender blocklist** — block individual addresses or entire domains; blocked messages are automatically moved to a dedicated `MailSweep-Blocked` IMAP folder for review rather than deleted; supports a local blocklist (stored in SQLite) and an optional community blocklist (synced from any raw `.txt` URL); both lists are managed from Actions → Manage Blocklist

## Installation

### macOS / Linux

**Option A — Standalone executable (no Python required)**

Download the latest release for your platform from the [releases page](https://github.com/jitrc/MailSweep/releases/latest):
- **macOS:** `MailSweep-macos.dmg` — open the DMG and drag MailSweep to Applications
- **Linux:** `MailSweep-linux.AppImage` — make executable and run: `chmod +x MailSweep-linux.AppImage && ./MailSweep-linux.AppImage`

**Option B — Run from source**

```bash
# Clone and install
git clone https://github.com/jitrc/MailSweep.git
cd MailSweep
uv sync --dev

# Run the GUI
uv run mailsweep

# Run the CLI (prints folder sizes, no GUI)
uv run mailsweep-cli --host imap.gmail.com --username you@gmail.com
```

### Windows

**Option A — Standalone executable (no Python required)**

Download `MailSweep-windows.exe` from the [latest release](https://github.com/jitrc/MailSweep/releases/latest) and double-click to run. Windows Defender SmartScreen may warn about an unrecognised publisher — click **More info → Run anyway**.

**Option B — Run from source**

1. Install [Python 3.11+](https://www.python.org/downloads/windows/) (check "Add Python to PATH" during setup)
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/):
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
3. Clone and run:
   ```powershell
   git clone https://github.com/jitrc/MailSweep.git
   cd MailSweep
   uv sync --dev
   uv run mailsweep
   ```

**Windows notes:**
- Credentials are stored in **Windows Credential Manager** (not in any file)
- The SQLite cache is stored at `%LOCALAPPDATA%\mailsweep\mailsweep.db`
- Settings are stored at `%APPDATA%\mailsweep\settings.json`
- The community blocklist cache is at `%APPDATA%\mailsweep\community_blocklist.txt`

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

### Outlook / Hotmail Setup

Microsoft has **disabled basic password authentication** for all Outlook.com and Hotmail consumer accounts. Password auth will fail with `BasicAuthBlocked`.

**OAuth2 is the only supported method**, but it has requirements:

- You must register an Azure app and obtain a Client ID
- App registration requires a **Microsoft 365 Developer account** or a **work/school Microsoft account** (e.g. a company Azure tenant)
- Personal Outlook.com / Hotmail accounts cannot create OAuth2 app registrations without one of the above

**Workaround:** If you do not have access to an Azure tenant, consider exporting your mail via [Outlook's export tool](https://support.microsoft.com/en-us/office/export-or-backup-email-contacts-and-calendar-to-an-outlook-pst-file-14252b52-3075-4e9b-be4e-ff9ef1068f91) and importing into a provider that supports app passwords (Gmail, Yahoo, Fastmail).

### Other Providers

| Provider | Host | Port | Auth |
|----------|------|------|------|
| Gmail | imap.gmail.com | 993 | App Password or OAuth2 |
| Outlook / Hotmail | outlook.office365.com | 993 | OAuth2 only (Microsoft has disabled basic password auth for consumer accounts) |
| Yahoo | imap.mail.yahoo.com | 993 | App Password |
| ProtonMail | 127.0.0.1 | 1143 | Bridge password |
| Fastmail | imap.fastmail.com | 993 | App Password |

## Feature Guide

### Treemap Visualization

The treemap at the bottom of the window shows your mailbox as a proportional area chart —
bigger tiles mean more storage consumed. It updates instantly when you select a folder or
change the view mode.

**View modes** (tabs above the treemap):

| Mode | What each tile represents | Best used for |
|------|--------------------------|---------------|
| **Folders** | One tile per folder/label, sized by total message bytes | Finding which folders are bloated |
| **Senders** | One tile per unique sender email, sized by total bytes from that sender | Identifying who is flooding your inbox with large mail |
| **Receivers** | One tile per recipient address, sized by total bytes to that address | Useful in Sent folders to see who you send large mail to |
| **Messages** | One tile per individual message, sized by message size | Finding the single largest messages to delete |
| **Count** | One tile per sender, sized by number of emails received from that sender | Spotting spammers — a single address sending 50+ emails shows up as a large tile even if the individual messages are small |

**Drill-down (Folders mode):** Click any folder tile to zoom into its sub-labels. Click a
leaf folder to see its top individual messages. Click **All Folders** in the left tree to
zoom back out.

**Click to filter:** Clicking a sender or receiver tile in the treemap automatically populates
the filter bar so only messages from/to that address are shown in the message table.

---

### Sender / Receiver Column

The message table shows either a **From** or **To** column depending on which folder you are
viewing:

- **From** (default) — shows who sent the message. Useful for Inbox, newsletters, any folder
  where you are the recipient.
- **To** — shown automatically when you select a Sent folder (MailSweep detects folder names
  like "Sent", "Sent Mail", "Sent Items"). Useful to see who you emailed and how much storage
  those sent messages occupy.

You can toggle between From and To manually using the **From / To** button in the toolbar.
MailSweep remembers your choice per folder for the session.

---

### Unlabelled Messages (Gmail)

Gmail uses labels rather than folders. Every message lives in **All Mail** and is tagged with
one or more labels (Inbox, Starred, your custom labels, etc.). A message is **unlabelled** when
it exists in All Mail but carries no label that maps to a visible folder — it was archived
directly without any label, so it never shows up in your normal folder browsing.

**Why it matters:** Unlabelled messages are invisible in the standard Gmail interface unless you
search `in:all`. Over years of archiving, these can accumulate into gigabytes of storage you
cannot easily find or clean.

**How to use it:** After scanning, an **Unlabelled** item appears in the folder tree (italic,
below All Folders). Clicking it loads only these hidden messages. You can then filter, sort by
size, and bulk-delete or backup them.

**Detection modes** (Settings → Unlabelled detection):

| Mode | How it works | When to use |
|------|-------------|-------------|
| **No thread matching** | A message is unlabelled if its exact Message-ID does not appear in any other label folder | Fast, accurate for most cases |
| **In-Reply-To chain** | Also considers a message labelled if any message in the same reply thread has a label | Reduces false positives when only the first reply is labelled |
| **Gmail Thread ID** | Uses Gmail's native X-GM-THRID to group threads; unlabelled if the entire thread has no label | Most accurate for Gmail, requires a Gmail account |

> **Note:** Unlabelled detection requires All Mail to be enabled. If you have disabled All Mail
> in Settings, this feature will not work.

---

### Finding Duplicate Labels (Cross-Label Duplicates)

**Actions → Find Duplicate Labels**

Gmail labels let the same physical message appear in multiple label-folders simultaneously
(e.g., a message in both Inbox and a custom label shows up twice when scanning). This tool
finds messages stored under two or more labels and shows them grouped together.

**Why it matters:** When you export or analyse your mailbox, duplicate labels inflate apparent
size. More importantly, if you manually created duplicate copies (e.g., by forwarding to yourself
or by having filters file into multiple labels), this surfaces them for cleanup.

**All Mail is skipped by default** — every labelled message also appears in All Mail, so
including it would make every message look like a duplicate. MailSweep asks whether to skip it
automatically; if you have disabled All Mail in Settings it is always excluded.

**How to use it:**
1. Run **Actions → Find Duplicate Labels**
2. The table shows each group of duplicates with a "N labels" badge
3. Sort by size, identify the copies you do not need
4. Select and delete the extras — the message is only truly removed when all copies are deleted

---

### Finding Detached Duplicates

**Actions → Find Detached Duplicates**

When you use MailSweep's **Detach Attachments** operation (or Thunderbird's equivalent), the
original large message is replaced with a lightweight version. However, the original sometimes
survives in another folder — typically **All Mail** on Gmail, or alongside the detached copy
in the same folder on other providers.

This tool finds pairs of messages where:
- Both copies have the same sender, subject, and date
- One is significantly larger than the other (the original with the attachment still intact)

**Why it matters:** The whole point of detaching is to save space. If the bloated original is
still sitting in All Mail, you have not saved anything. This scan surfaces those orphaned
originals so you can delete them and actually reclaim the storage.

**How to use it:**
1. Run **Actions → Find Detached Duplicates**
2. Each row is tagged **Original** or **Detached Copy**
3. Review the pairs — confirm the smaller copy has the placeholder text you expect
4. Select the **Original** rows and delete them to reclaim space

> **Note:** Finding detached duplicates in All Mail requires All Mail to be enabled in Settings.

---

### Bulk Unsubscribe

**Right-click → Unsubscribe (N msg(s))** or **Unsubscribe && Delete (N msg(s))**

Select one or more messages in the message table, then right-click to unsubscribe from their
mailing lists. MailSweep reads the `List-Unsubscribe` and `List-Unsubscribe-Post` headers from
each message and handles the unsubscribe automatically:

| Header present | What MailSweep does |
|---------------|---------------------|
| `List-Unsubscribe-Post: List-Unsubscribe=One-Click` + HTTPS URL | Silent HTTP POST per RFC 8058 — no browser needed |
| HTTPS URL only (no one-click header) | Opens a sandboxed browser tab for you to complete the form |
| Mailto only | Skipped (no SMTP support) |
| No unsubscribe header | Skipped |

**Deduplication:** If you select 50 messages from the same newsletter, MailSweep sends the
unsubscribe request exactly once — subsequent messages with the same URL are marked
`duplicate_skipped` without making a second request.

**Sandboxed browser:** When a manual confirmation page is required, MailSweep opens it in an
isolated, off-the-record browser view. Cross-origin navigation is blocked, JavaScript window
popups are disabled, and nothing is saved to your browser profile.

**Unsubscribe && Delete:** Runs the unsubscribe step first, then moves all selected messages to
Trash in one batched operation — useful for cleaning up a mailing list in one action.

---

### AI Assistant

**View → Show AI Assistant**

The AI assistant analyses your mailbox and suggests actions in plain English. It works
entirely from the local SQLite cache — no message bodies are sent to the LLM, only
aggregated statistics (folder sizes, top senders, cross-folder overlap, inactive folders).

**When to use it:**

| Situation | What to ask |
|-----------|-------------|
| You have hundreds of folders and do not know where to start | Ask "which folders are wasting the most space?" |
| A sender you don't recognise is consuming gigabytes | Ask "who are the top senders by size and should I unsubscribe?" |
| You suspect some folders are redundant or overlap | Ask "are there senders who appear in multiple folders?" or "which folders seem dead?" |
| You want suggested cleanup rules | Ask "suggest a cleanup plan for my mailbox" |
| You want to reorganise labels | Ask "which messages in Inbox belong in a specific label?" |

**Applying suggestions:** When the AI suggests moving messages to a different folder,
an **Apply Moves** button appears. Clicking it executes the IMAP moves directly — MailSweep
handles the folder creation and move commands, and you confirm each batch before anything changes.

**Provider setup** (Settings → AI Assistant):

| Provider | Base URL | Key needed | Best for |
|----------|----------|-----------|---------|
| Ollama | http://localhost:11434/v1 | No | Free, private, runs locally |
| LM Studio | http://localhost:1234/v1 | No | Free, private, runs locally |
| OpenAI | (auto-filled) | Yes | GPT-4o, most capable cloud option |
| Anthropic | (auto-filled) | Yes | Claude, strong reasoning |
| Custom | Any OpenAI-compatible URL | Optional | Self-hosted or proxy endpoints |

Use the **Refresh** button next to the model dropdown to discover all models currently
loaded on your local Ollama or LM Studio instance.

---

### Senders Sidebar

The **Senders** tab in the left panel shows all unique senders for the current account, sorted by message count. Click any sender to filter the message table to only their messages. Right-click for the full action menu (same options as Sender List below). Excludes Trash and MailSweep-Blocked from counts. Updates automatically when you switch accounts.

---

### Sender List

**Actions → Sender List…**

Shows all unique senders across your mailbox in a sortable, searchable table with message count and total size. The status bar shows the total size across all displayed senders, and updates to show the selected count and size when rows are highlighted. Useful for quickly identifying who is flooding your inbox.

- **Filter** — type to narrow down by email address
- **Sort** — click any column header to sort; defaults to message count descending
- **Multi-select** — Ctrl+click or Shift+click to select multiple senders
- **Right-click → Delete All From sender(s)** — move all messages from selected senders to Trash
- **Right-click → Block && Delete All From sender(s)** — add to blocklist and move to Trash
- **Right-click → Backup && Delete All From sender(s)** — download as .eml files then move to Trash
- **Right-click → Permanent Delete All From sender(s)** — immediately expunge without moving to Trash
- **Right-click → Block && Permanent Delete All From sender(s)** — add to blocklist and permanently expunge

---

### Sender Blocklist

**Actions → Manage Blocklist**

Block individual email addresses or entire domains from appearing in your inbox. Blocked messages are moved to a dedicated **`MailSweep-Blocked`** IMAP folder (not Trash) so you can review them before permanently deleting.

**Adding senders to the blocklist:**
- Right-click → **Unsubscribe && Block** — sends an unsubscribe request and adds the sender to your local blocklist
- Right-click → **Unsubscribe, Block && Delete** — unsubscribes, adds to blocklist, and deletes selected messages
- Right-click → **Delete All From Sender** — deletes all messages from that sender across the entire account (does not add to blocklist)
- Open **Actions → Manage Blocklist** to add patterns manually

**Post-scan detection:** During every scan, MailSweep checks only newly fetched messages against the blocklist (for performance — existing messages are never re-checked). Messages already in `MailSweep-Blocked` are skipped during the blocklist check since they are already in the right place. If blocked senders are found among new messages, you are prompted to move them. Enable **Auto-move** (in Settings or via the prompt checkbox) to move them silently without asking.

**Blocklist Manager** (Actions → Manage Blocklist) has two tabs:

| Tab | What it does |
|-----|-------------|
| **Local** | Add/remove/edit individual patterns; double-click a row to edit it; export to `.txt`; import from `.txt` |
| **Community** | Enable/disable a community-sourced blocklist; enter any raw `.txt` URL (e.g. a GitHub raw link); Sync downloads and caches the list locally; you can also manually add, remove, or edit entries and save them |

**Pattern format:**
- `spam@example.com` — block a specific address
- `@example.com` — block an entire domain

**Community blocklist:** Point the URL to any publicly hosted `.txt` file (one pattern per line, `#` for comments). The list is stored locally at `~/.config/mailsweep/community_blocklist.txt` and is never merged into the local SQLite database — the two lists remain independent.

---

### All Mail (Gmail) — Disable Option

Gmail's All Mail folder is a virtual folder containing every message regardless of label.
Scanning it doubles the apparent size of your mailbox and can cause confusion in counts,
treemaps, and duplicate searches since every message appears at least twice.

**Settings → Disable All Mail folder** excludes All Mail from:
- Syncing (it is never scanned)
- Folder tree and size counts
- Treemap visualization
- Message table queries when "All Folders" is selected
- Duplicate label and detached duplicate searches

> **Trade-off:** Disabling All Mail means Unlabelled email detection and Find Detached Duplicates
> will not work, since both rely on All Mail as the source of truth for archived messages.

---

## Operations

| Operation | Server Modified? | Description |
|-----------|-------------------|-------------|
| **Extract Attachments** | No | Save attachments to local disk |
| **Detach Attachments** | Yes | Save locally + replace attachment in message with placeholder |
| **Backup** | No | Download full message as .eml file |
| **Backup & Delete** | Yes | Download .eml then move message to Trash |
| **Delete** | Yes | Move message to Trash (Gmail-safe) |
| **Permanent Delete** | Yes | Immediately expunge without moving to Trash |
| **Unsubscribe && Block** | No | Send unsubscribe request and add sender to local blocklist |
| **Unsubscribe, Block && Delete** | Yes | Unsubscribe, add sender to local blocklist, then move messages to Trash |
| **Delete All From Sender** | Yes | Move all messages from that sender to Trash |
| **Permanent Delete All From Sender** | Yes | Immediately expunge all messages from that sender without moving to Trash |
| **Block && Permanent Delete All From Sender** | Yes | Add to blocklist and permanently expunge all messages from that sender |
| **Empty Trash** | Yes | Permanently expunge all messages in the Trash folder |
| **AI Move** | Yes | LLM suggests moves → user confirms → messages moved via IMAP |

### Extract vs Detach

Both operations save attachments to your local disk, but they differ in what happens to the server message:

**Extract Attachments** — read-only. The attachment is copied to disk and the original message on the server is left completely untouched. Use this when you want a local copy of a file but still want the full message to remain in your mailbox (e.g. contracts, receipts you may need to forward).

**Detach Attachments** — modifies the server. The attachment is saved locally, then the message on the server is rewritten: the attachment part is replaced with a small text/plain placeholder that records the local file path. The message subject, body text, and metadata are preserved. Use this to permanently reclaim storage — a 10 MB PDF attachment becomes a few hundred bytes on the server while the file lives on your disk.

> After detaching, run **Actions → Find Detached Duplicates** to catch any orphaned originals that survived in other folders (common on Gmail's All Mail).

### Backup vs Backup & Delete

**Backup** — downloads the complete message as a standard `.eml` file (RFC 822 format, openable in any email client) and leaves the server message intact. Use this to archive important messages locally before cleaning up, or to migrate mail between providers.

**Backup & Delete** — same download, then immediately moves the message to Trash. This is the safe way to remove messages you want to keep a local copy of. On Gmail, the move goes to `[Gmail]/Trash` rather than expunging directly, so there is a recovery window before Gmail permanently deletes it.

## Data Locations

| Item | Path |
|------|------|
| SQLite cache | `~/.local/share/mailsweep/mailsweep.db` |
| Settings | `~/.config/mailsweep/settings.json` |
| Community blocklist cache | `~/.config/mailsweep/community_blocklist.txt` |
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
