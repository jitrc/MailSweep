# MailSweep — Progress & Plan

**Last updated:** 2026-02-24
**Status:** All 6 phases implemented. App running. ~3,800 lines of Python. 41/41 tests passing.

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
│   │   ├── connection.py          ← connect() — password + OAuth2 dispatch
│   │   └── oauth2.py              ← Gmail XOAUTH2, Outlook MSAL, token refresh
│   ├── workers/
│   │   ├── scan_worker.py         ← FETCH ENVELOPE+SIZE+BODYSTRUCTURE, batched
│   │   ├── qt_scan_worker.py      ← QObject wrapper (moveToThread), incremental
│   │   ├── detach_worker.py       ← FETCH→strip→APPEND→DELETE→EXPUNGE
│   │   ├── backup_worker.py       ← RFC822→.eml→DELETE→EXPUNGE
│   │   └── incremental_scan.py    ← get_new_deleted_uids(), CONDSTORE check
│   └── ui/
│       ├── main_window.py         ← QMainWindow, splitter layout, all wiring
│       ├── account_dialog.py      ← add/edit account, OAuth2 on background thread
│       ├── folder_panel.py        ← QTreeWidget with size badges
│       ├── message_table.py       ← QTableView + MessageTableModel + ProxyModel
│       ├── filter_bar.py          ← sender/subject/date/size/attachment filters
│       ├── treemap_widget.py      ← squarify + QPainter, hover, click-to-filter
│       ├── progress_panel.py      ← QProgressBar + status + Cancel
│       ├── settings_dialog.py     ← batch size, max rows, save dir
│       └── log_dock.py            ← live log viewer, per-level colour, dockable
└── tests/
    ├── test_db.py                 ← 15 tests: CRUD, queries, stats
    ├── test_scan_worker.py        ← 15 tests: mock IMAP, BODYSTRUCTURE parser
    └── test_mime_utils.py         ← 11 tests: strip, save, path traversal
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

---

## Bugs Fixed Post-Implementation

| Bug | Fix |
|-----|-----|
| BODYSTRUCTURE multipart: only `bs[0]` walked, siblings missed | Walk all items in the list that are list/tuple |
| `run_local_server()` blocked Qt event loop on OAuth2 | Moved to `_OAuthWorker` on background `QThread` |
| OAuth2 dialog gave no context on Client ID/Secret | Added inline help + links + App Password recommendation |
| Rescan re-fetched all UIDs every time | Incremental scan: diff UIDs, fetch only delta |

---

## Known Gaps / Next Steps

### High priority
- [ ] **Sender aggregation view** — group-by-sender sub-table showing total size per sender
      (repo method `get_sender_summary()` exists, no UI widget yet)
- [ ] **"Reload from Cache" on startup** — currently shows data immediately but the
      folder tree size badges only populate after a scan; should derive sizes from DB on load
- [ ] **Error recovery on scan** — if a folder errors mid-scan, resume from next folder
      (partially done — errors are logged and scan continues to next folder)

### Medium priority
- [ ] **Delete confirmation shows total size** — "Delete 3 messages (47 MB)?" is more useful
- [ ] **Progress panel for delete** — in-thread delete blocks the GUI momentarily on large batches;
      move to worker thread
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

## Git Log

```
9eb8130  feat: incremental scan — only fetch new UIDs on rescan
a5918ee  fix: OAuth2 browser flow on background thread, better UX in account dialog
37fa29d  feat: phases 5-6 — OAuth2, incremental scan, settings, log dock, packaging
48796bc  feat: phases 2-4 — GUI, scan worker, filter bar, treemap, detach, backup-delete
c10f3a1  feat: phase 1 — data layer, IMAP scan, CLI script
```
