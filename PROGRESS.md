# MailSweep — Progress & Plan

**Last updated:** 2026-02-25
**Status:** All 7 phases implemented. App running. ~6,500 lines of Python. 85/85 tests passing. Published on GitHub. Version 0.4.1.

---

## What Is Built

### Stack
- Python 3.13 · PyQt6 · imapclient · squarify · SQLite (stdlib) · keyring
- Package manager: `uv` — `uv sync --dev` · `uv run mailsweep` · `uv run pytest`

### Project Layout
```
mailsweep/                         ← project root
├── pyproject.toml
├── mailsweep.spec                 ← PyInstaller packaging spec
├── mailsweep/                     ← Python package
│   ├── main.py                    ← GUI entry point
│   ├── cli.py                     ← CLI: prints folder sizes
│   ├── config.py                  ← paths, defaults
│   ├── models/
│   │   ├── account.py             ← Account dataclass + AuthType enum
│   │   ├── folder.py              ← Folder dataclass
│   │   └── message.py             ← Message dataclass (from_row, JSON fields)
│   ├── db/
│   │   ├── schema.py              ← init_db(), CREATE TABLE + indexes
│   │   └── repository.py          ← AccountRepo, FolderRepo, MessageRepo
│   ├── imap/
│   │   ├── connection.py          ← connect(), find_trash_folder(), list_folders()
│   │   └── oauth2.py              ← Gmail XOAUTH2, Outlook MSAL, token refresh
│   ├── ai/
│   │   ├── providers.py           ← LLM abstraction: OpenAI-compat + Anthropic (stdlib HTTP)
│   │   └── context.py             ← DB→markdown context builder for LLM
│   ├── workers/
│   │   ├── scan_worker.py         ← FETCH ENVELOPE+SIZE+BODYSTRUCTURE, batched
│   │   ├── qt_scan_worker.py      ← QObject wrapper (moveToThread), incremental
│   │   ├── detach_worker.py       ← FETCH→strip→APPEND→DELETE→EXPUNGE
│   │   ├── backup_worker.py       ← RFC822→.eml→DELETE→EXPUNGE
│   │   ├── delete_worker.py       ← Gmail-safe delete on background thread
│   │   ├── incremental_scan.py    ← get_new_deleted_uids(), CONDSTORE check
│   │   ├── ai_worker.py           ← background LLM chat (moveToThread)
│   │   └── move_worker.py         ← IMAP MOVE (RFC 6851) with copy+delete fallback
│   └── ui/
│       ├── main_window.py         ← QMainWindow, splitter layout, all wiring
│       ├── account_dialog.py      ← add/edit account, OAuth2 on background thread
│       ├── folder_panel.py        ← QTreeWidget with size badges
│       ├── message_table.py       ← QTableView + MessageTableModel + ProxyModel
│       ├── filter_bar.py          ← sender/subject/date/size/attachment filters
│       ├── treemap_widget.py      ← squarify + QPainter, hover, click-to-filter
│       ├── progress_panel.py      ← QProgressBar + status + Cancel
│       ├── settings_dialog.py     ← batch size, max rows, save dir, AI settings
│       ├── log_dock.py            ← live log viewer, per-level colour, dockable
│       └── ai_dock.py             ← AI chat dock: provider selector, chat history, apply moves
└── tests/
    ├── test_db.py                 ← 22 tests: CRUD, queries, stats, message_id matching
    ├── test_scan_worker.py        ← 17 tests: mock IMAP, BODYSTRUCTURE parser, message_id
    ├── test_mime_utils.py         ← 11 tests: strip, save, path traversal
    └── test_ai.py                 ← 18 tests: LLM providers, context builder, AI queries
```

---

## Phase Completion

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Models, DB, scan worker, CLI | ✅ done |
| 2 | Core GUI + scan wired to table | ✅ done |
| 3 | Filter bar + treemap + sender view | ✅ done |
| 4 | Detach attachments + backup-delete | ✅ done |
| 5 | Gmail + Outlook OAuth2 | ✅ done |
| 6 | Incremental scan, settings, log dock, packaging spec | ✅ done |
| 7 | AI-powered email analysis & reorganization | ✅ done |

---

## Key Design Decisions & How They Were Resolved

### Scan (no full message download)
`FETCH [ENVELOPE, RFC822.SIZE, BODYSTRUCTURE]` — sender/subject/date/size/MIME tree
with no body bytes.  Batched in groups of 500 UIDs.  BODYSTRUCTURE parsed recursively;
fix: walk **all sibling parts** in a multipart (not just `bs[0]`).

### Incremental Rescan (implemented in post-phase-6 fix)
On rescan, `QtScanWorker` now:
1. Checks `UIDVALIDITY` — if changed, wipes folder cache and does full FETCH
2. If cache valid: calls `get_new_deleted_uids()` → diffs server UID list vs DB
3. Only FETCHes new UIDs; prunes deleted UIDs from DB
4. If nothing changed, skips FETCH entirely — rescan finishes in seconds

### OAuth2 (post-phase-5 fix)
`InstalledAppFlow.run_local_server()` blocks — runs in `_OAuthWorker` on a `QThread`.
Account dialog shows inline help with links to Google Cloud Console / Azure Portal.
Recommends **Gmail App Password** as the simpler alternative (no cloud project needed).

### Threading
All IMAP I/O in QObject workers → `moveToThread` pattern.
Cancel: `_cancel_requested = True` flag checked between batches.

### Attachment Detach
`compat32` policy preserves wire format for safe re-upload.
`_parse_bodystructure` detects by `Content-Disposition: attachment` or filename+type heuristic.
Audit header `X-MailSweep-Detached` added to stripped message.
Path traversal sanitised in `_safe_filename`.
Detached parts replaced with text/plain placeholder (original name, size, local path).

### Gmail-Safe Delete
Gmail's IMAP maps `\Deleted`+`EXPUNGE` on `[Gmail]/All Mail` to permanent deletion (bypasses Trash).
Fix: `COPY` UIDs to `[Gmail]/Trash` before `\Deleted`+`EXPUNGE`. Applied to inline delete and backup worker.
Detach worker doesn't need this — it APPENDs a replacement message, so the old one should be removed.
`find_trash_folder()` in `connection.py` detects Trash across providers (Gmail, Outlook, Apple Mail, generic).

### AI-Powered Analysis (Phase 7)
LLM integration via stdlib HTTP (`urllib.request`) — zero new dependencies.
- **Providers:** OpenAI-compatible (Ollama, OpenAI, Groq, Together) + Anthropic native API
- **Context builder:** Reads SQLite DB → markdown summary (folder tree with stats, top senders per folder,
  cross-folder sender overlap, dead folder detection). Capped at ~8K tokens.
- **AI dock:** `QDockWidget` with chat history, provider/model selector, quick-action buttons
  ("Analyze folders", "Find misfilings", "Find duplicates"), and "Apply Suggestions" for MOVE operations
- **Move worker:** IMAP MOVE (RFC 6851) with `COPY`+`DELETE`+`EXPUNGE` fallback, batched by source folder,
  updates local DB cache after each move
- **Threading:** `AiWorker` uses `@pyqtSlot` + `moveToThread` pattern (params via constructor, not lambda)
  to keep UI responsive during LLM calls
- **Settings:** Provider/URL/model persisted in `settings.json`; API key stored in system keyring

---

## Bugs Fixed Post-Implementation

| Bug | Fix |
|-----|-----|
| BODYSTRUCTURE multipart: only `bs[0]` walked, siblings missed | Walk all items in the list that are list/tuple |
| `run_local_server()` blocked Qt event loop on OAuth2 | Moved to `_OAuthWorker` on background `QThread` |
| OAuth2 dialog gave no context on Client ID/Secret | Added inline help + links + App Password recommendation |
| Rescan re-fetched all UIDs every time | Incremental scan: diff UIDs, fetch only delta |
| Size sorting compared strings ("1.2 KB" > "3.4 MB") | Added sort role (UserRole+1) returning raw `size_bytes` int |
| Gmail labels double-counted mailbox size (8 GB shown vs 4 GB actual) | SQL DISTINCT dedup + server IMAP QUOTA for real usage |
| Treemap Messages view: click on message did nothing | Clear filters + `select_by_uid` + scroll to center |
| Worker threads garbage collected before running | Store `_op_worker`/`_op_thread` as instance vars with cleanup |
| Gmail delete permanently removed messages (bypassed Trash) | COPY to `[Gmail]/Trash` before `\Deleted`+`EXPUNGE` |
| Detach didn't modify original email on server | Added `readonly=False` to `select_folder`, added logging |
| Detached attachments left no trace in email | Replace with text/plain placeholder (filename, size, local path) |
| Settings save dir not taking effect for extract/backup | Changed `from config import X` to `import config as cfg` (live lookup) |
| Senders with different display names grouped separately | Extract email with SQL `INSTR`/`SUBSTR`, group by lowercase email |
| Delete ran on main thread (GUI freeze) | Created `DeleteWorker` on background `QThread` |
| Dangerous full EXPUNGE fallback if UID EXPUNGE unsupported | Changed to warning log instead of expunging all `\Deleted` messages |
| Filter bar "From:" label on date picker | Fixed to "Date:" |
| Date filters missing from `get_filter_kwargs()` | Added `date_from`/`date_to` to filter bar output |
| Dead code `_unwrap_single_child()` in mime_utils | Removed |
| `_walk_and_strip` docstring/return type wrong | Fixed return type from `bool` to `None` |
| Settings not persisted across sessions | Added `save_settings()`/`load_settings()` in config.py |
| Hardcoded "[Gmail]/Trash" in delete dialog | Dynamic trash folder name via `find_trash_folder()` |
| DB writes had no rollback on error | Added `_safe_commit()` context manager to all 7 write methods |
| Outlook token refresh returned expired token | Return `None` on refresh failure instead of stale token |
| Bare `except: pass` in BODYSTRUCTURE parser | Added `logger.debug()` for diagnostics |
| Worker callbacks could fire on dead widget after close | Added `_is_closing` guard in `closeEvent` and `_on_op_finished` |
| Log handler accumulated on dock widget recreate | Remove handler in `destroyed` signal |
| Treemap hover highlight stuck after mouse leaves | Added `leaveEvent` to clear `_hovered_key` |
| Unlabelled folder included messages with labels (e.g. OLD/2016) | Added `message_id` (RFC 5322) to schema; cross-folder matching now uses globally unique ID |
| View Headers only showed single folder, not all Gmail labels | `get_folders_for_message()` queries all folders sharing same `message_id`; dialog shows "Labels:" |
| Folder panel stale after settings change | Added `_refresh_folder_panel()` + `_reload_messages()` after settings dialog accepted |
| Unlabelled stats stale after scan completes | Added `_refresh_folder_panel()` + `_refresh_size_label()` to `_on_scan_all_done()` |
| Dots in folder names treated as hierarchy separators | Removed `.replace(".", "/")` in folder panel — only split on `/` (Gmail delimiter) |
| AppImage `execv error: No such file or directory` | YAML heredoc indentation added leading whitespace to `.desktop` Exec= line; fixed with `sed` strip |

---

## Post-Phase Enhancements (completed)

| Feature | Details |
|---------|---------|
| **Treemap view modes** | Three modes: Folders, Senders, Messages — switchable via combo box |
| **Treemap folder drill-down** | Click folder → shows sub-labels; click sub-label → shows messages; hierarchical navigation |
| **Backup without delete** | "Backup…" button/menu saves .eml files without removing from server |
| **Extract without detach** | "Extract Attachments…" saves attachments locally without modifying server message |
| **Status bar quota display** | Shows "Google: X / Y (Z%) \| Mail: A (B msgs)" using IMAP QUOTA |
| **Dedup folder sizes** | "All Folders" shows deduplicated total (Gmail labels don't inflate count) |
| **Attachment placeholder** | Detached attachments replaced with text/plain showing original name, size, local path |
| **Gmail-safe delete** | COPY to [Gmail]/Trash before EXPUNGE (prevents permanent deletion) |
| **Organized save paths** | Attachments saved to `<label>/<uid>_<subject>/` matching backup folder structure |
| **Delete worker thread** | Delete operation moved off main thread to `DeleteWorker` with progress signals |
| **Settings persistence** | Batch size, max rows, save dir saved to `~/.config/mailsweep/settings.json` |
| **Sender email dedup** | Sender treemap/summary groups by extracted email, not full "Name \<email\>" string |
| **Message-ID matching** | `message_id` from ENVELOPE used for cross-folder dedup, unlabelled detection, and "View Headers → Labels" |
| **Force Full Rescan** | Actions menu option to re-fetch all message metadata, bypassing incremental cache |
| **AI Assistant** | LLM chat dock for mailbox analysis — Ollama/OpenAI/Anthropic, zero new deps (stdlib HTTP) |
| **AI folder analysis** | Context builder: folder tree, top senders, cross-folder overlap, dead folder detection |
| **AI move suggestions** | LLM outputs `MOVE:` lines → user confirms → IMAP move worker executes |
| **IMAP move worker** | RFC 6851 MOVE with copy+delete fallback, batched by source folder, DB cache update |
| **AI settings** | Provider/URL/model in settings dialog + keyring for API key |
| **Move to… (manual)** | "Move to…" toolbar button + context menu action — folder picker dialog, reuses MoveWorker |
| **Thread-aware unlabelled** | Three modes for unlabelled detection: message-id only, in-reply-to chain, Gmail thread ID |
| **Find Detached Duplicates** | Detect Thunderbird-style detach leftovers (original + stripped copy in same folder) |
| **Find Duplicate Labels** | Find messages appearing in 2+ IMAP folders (cross-label duplicates), skip All Mail option |
| **Toolbar theme icons** | System theme icons on all toolbar buttons; App Password help shown when host is blank |
| **AI sender-based moves** | AI MOVE suggestions use `sender=` format (not UID); resolved to concrete UIDs at apply time |
| **App icon** | SVG icon (envelope + treemap blocks + sparkles); set on QApplication, bundled in PyInstaller spec |
| **Screenshots in README** | 8 screenshots added: treemap views, unlabelled, AI suggestions, account settings, settings |
| **Author metadata** | Author name in pyproject.toml, README, and About dialog |
| **Remove Label** | Expunge messages from specific folders without Trash copy; for cleaning up duplicate labels |
| **Label picker dialog** | Remove Label shows all folders a message appears in with checkboxes; user picks which to remove |

---

## Known Gaps / Next Steps

### High priority
- [x] ~~**Sender aggregation view**~~ — implemented as treemap "Senders" mode
- [ ] **"Reload from Cache" on startup** — folder tree size badges only populate after scan;
      should derive sizes from DB on load
- [ ] **Error recovery on scan** — if a folder errors mid-scan, resume from next folder
      (partially done — errors are logged and scan continues to next folder)

### Medium priority
- [ ] **Delete confirmation shows total size** — "Delete 3 messages (47 MB)?" is more useful
- [x] ~~**Progress panel for delete**~~ — moved to `DeleteWorker` on background `QThread`
- [ ] **Post-detach incremental re-sync** — after detach/backup, new UIDs should be picked up
      without a full rescan (currently requires manual "Scan Mailbox")
- [ ] **CONDSTORE / HIGHESTMODSEQ** — `supports_condstore()` helper exists but not used;
      would allow detecting changed flags cheaply on capable servers
- [ ] **ProtonMail Bridge** — document that it works via 127.0.0.1:1143 with password auth

### Low priority / nice-to-have
- [ ] **Dark mode** — QPalette theming
- [ ] **Column chooser** — show/hide columns in message table
- [ ] **Export CSV** — save current table view as CSV
- [ ] **PyInstaller build tested** — spec file written, not yet tested end-to-end
- [ ] **Briefcase / AppImage** — cross-platform packaging alternative to PyInstaller
- [ ] **pytest-qt GUI tests** — currently all tests are headless (DB + workers);
      add smoke tests for main window open/close

---

## Running

```bash
# GUI
uv run mailsweep

# CLI (prints folder sizes, no GUI needed)
uv run mailsweep-cli --host imap.gmail.com --username you@gmail.com

# Tests
uv run pytest

# Lint
uv run ruff check mailsweep/
```

## Data locations

| Item | Path |
|------|------|
| SQLite cache | `~/.local/share/mailsweep/mailsweep.db` |
| Saved attachments | `~/MailSweep_Attachments/` |
| Backup .eml files | `~/MailSweep_Attachments/backups/` |
| App log | `~/.local/share/mailsweep/mailsweep.log` |

---

## Code Review (completed)

Full code review performed covering secrets, core logic, UI, and project config.
All critical, high, medium, and low priority issues resolved across 4 commits:

| Priority | Issues Found | Issues Fixed |
|----------|-------------|--------------|
| Critical | 7 | 7 |
| High | 6 | 6 |
| Medium | 5 | 5 |
| Low | 3 | 3 |

Key items: delete moved to worker thread, DB rollback safety, dangerous EXPUNGE fallback removed,
settings persistence, filter bar fixes, dead code removal, log handler leak, treemap hover fix,
Outlook token refresh fix, README/LICENSE/.gitignore added, pyproject.toml metadata.

---

## Git Log

```
ad6d4f2  feat: label picker dialog for Remove Label action
8321780  feat: add Remove Label action for duplicate labels cleanup
8c674f2  chore: bump version to 0.3.2, update PROGRESS.md
9fc48cb  feat: add app icon (envelope with treemap blocks and sparkles)
7f410b1  docs: add screenshots to README
d8d9ee1  docs: add author to pyproject.toml
f56aadc  docs: add author name to README and About dialog
1a7ae25  fix: change AI move suggestions from UID-based to sender-based format
023e852  feat: add theme icons to toolbar and show App Password help for blank host
067e359  feat: add Find Duplicate Labels action and show Gmail App Password help in password mode
cf2ad0c  feat: add Find Detached Duplicates action to detect Thunderbird detach leftovers
872c333  fix: bundle certifi CA certs for SSL in PyInstaller builds
8073172  fix: build macOS .app bundle instead of bare executable
b04403a  fix: strip leading whitespace from AppImage desktop file
0164f9a  fix: stop treating dots as folder hierarchy separators
4b1c44e  feat: add "Move to…" for messages + fix stale folder panel after settings/scan
30efb35  feat: add thread-aware unlabelled detection with three configurable modes
6a02667  chore: bump version to 0.3.0, update PROGRESS.md and README for AI feature
5f8a4d0  feat: add AI-powered email analysis and reorganization
2b552f4  feat: add AppImage build to release workflow
994e9fa  fix: build Linux binary on ubuntu-22.04 for GLIBC 2.35 compat
0b9d67d  chore: bump version to 0.2.0, update PROGRESS.md for release
52a2a44  refactor: remove schema migrations, inline all columns and indexes
8fbdba4  feat: add Force Full Rescan option in Actions menu
2817424  feat: add message_id for cross-folder matching, fix unlabelled detection
3161afd  feat: add GitHub Actions release workflow and update PyInstaller spec for onefile builds
6d005ec  feat: add virtual "Unlabelled" folder for archived-only Gmail messages
cbc8dd7  feat: toggleable From/To column, receiver treemap & To filter
0f22b1c  fix: medium/low priority code review issues
dd0523d  fix: merge senders by email address, use jitrc/MailSweep URLs
7470014  fix: code review — critical and high priority issues
e5828a3  fix: settings save dir not taking effect for extract/backup operations
b44f7de  fix: Gmail-safe delete (COPY to Trash before EXPUNGE), attachment placeholders
996e4da  fix: organize extracted attachments by label/subject like backup
61b69e9  feat: treemap drill-down, view modes, dedup sizes, backup/extract without delete
78b4c5c  feat: scan selected folder + auto-fetch folder list on account add/select
26b75cf  fix: parse imapclient 3.x Envelope/Address objects (attribute access, not index)
9eb8130  feat: incremental scan — only fetch new UIDs on rescan
a5918ee  fix: OAuth2 browser flow on background thread, better UX in account dialog
37fa29d  feat: phases 5-6 — OAuth2, incremental scan, settings, log dock, packaging
48796bc  feat: phases 2-4 — GUI, scan worker, filter bar, treemap, detach, backup-delete
c10f3a1  feat: phase 1 — data layer, IMAP scan, CLI script
```
