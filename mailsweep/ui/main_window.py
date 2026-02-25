"""Main application window — QMainWindow with splitter layout."""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import mailsweep.config as cfg
from mailsweep.config import DB_PATH
from mailsweep.db.repository import AccountRepository, FolderRepository, MessageRepository
from mailsweep.db.schema import init_db
from mailsweep.models.account import Account
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message
from mailsweep.ui.account_dialog import AccountDialog
from mailsweep.ui.filter_bar import FilterBar
from mailsweep.ui.folder_panel import UNLABELLED_ID, FolderPanel
from mailsweep.ui.message_table import MessageTableView
from mailsweep.ui.progress_panel import ProgressPanel
from mailsweep.ui.treemap_widget import (
    VIEW_FOLDERS,
    VIEW_MESSAGES,
    VIEW_RECEIVERS,
    VIEW_SENDERS,
    TreemapItem,
    TreemapWidget,
)
from mailsweep.utils.size_fmt import human_size
from mailsweep.workers.qt_scan_worker import QtScanWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MailSweep")
        self.resize(1280, 800)

        # DB
        self._conn = init_db(DB_PATH)
        self._account_repo = AccountRepository(self._conn)
        self._folder_repo = FolderRepository(self._conn)
        self._msg_repo = MessageRepository(self._conn)

        # State
        self._current_account: Account | None = None
        self._current_folder_ids: list[int] = []
        self._scan_thread: QThread | None = None
        self._scan_worker: QtScanWorker | None = None
        self._op_thread: QThread | None = None
        self._op_worker: object | None = None
        self._op_processed: dict[int, list[int]] = {}  # folder_id → [uids]
        self._op_needs_rescan = False
        self._op_updates_cache = False
        self._is_closing = False
        self._folder_show_to: dict[tuple[int, ...], bool] = {}  # folder_ids → show_to

        self._build_ui()
        self._load_accounts()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_central_widget()
        self._build_status_bar()
        self._build_menu()
        self._build_log_dock()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel("Account: "))
        self._account_combo = QComboBox()
        self._account_combo.setMinimumWidth(200)
        self._account_combo.currentIndexChanged.connect(self._on_account_changed)
        tb.addWidget(self._account_combo)

        tb.addSeparator()

        self._scan_btn = QPushButton("Scan All")
        self._scan_btn.clicked.connect(self._on_scan)
        tb.addWidget(self._scan_btn)

        self._scan_selected_btn = QPushButton("Scan Selected Folder")
        self._scan_selected_btn.clicked.connect(self._on_scan_selected)
        tb.addWidget(self._scan_selected_btn)

        self._extract_btn = QPushButton("Extract Attachments…")
        self._extract_btn.clicked.connect(lambda: self._on_extract_attachments())
        tb.addWidget(self._extract_btn)

        self._detach_btn = QPushButton("Detach Attachments…")
        self._detach_btn.clicked.connect(self._on_detach)
        tb.addWidget(self._detach_btn)

        self._backup_btn = QPushButton("Backup…")
        self._backup_btn.clicked.connect(lambda: self._on_backup_only())
        tb.addWidget(self._backup_btn)

        self._backup_delete_btn = QPushButton("Backup && Delete…")
        self._backup_delete_btn.clicked.connect(self._on_backup_delete)
        tb.addWidget(self._backup_delete_btn)

        self._delete_btn = QPushButton("Delete…")
        self._delete_btn.clicked.connect(self._on_delete)
        tb.addWidget(self._delete_btn)

    def _build_central_widget(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Filter bar (top)
        self._filter_bar = FilterBar()
        self._filter_bar.filter_changed.connect(self._on_filter_changed)
        main_layout.addWidget(self._filter_bar)

        # Horizontal splitter: [folder tree | right pane]
        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._folder_panel = FolderPanel()
        self._folder_panel.folder_selected.connect(self._on_folder_selected)
        h_splitter.addWidget(self._folder_panel)

        # Right pane: vertical splitter [message table | treemap]
        v_splitter = QSplitter(Qt.Orientation.Vertical)

        self._msg_table = MessageTableView()
        self._msg_table.extract_requested.connect(self._on_extract_messages)
        self._msg_table.detach_requested.connect(self._on_detach_messages)
        self._msg_table.backup_requested.connect(self._on_backup_messages_only)
        self._msg_table.backup_delete_requested.connect(self._on_backup_messages)
        self._msg_table.delete_requested.connect(self._on_delete_messages)
        self._msg_table.view_headers_requested.connect(self._on_view_headers)
        self._msg_table.show_to_toggled.connect(self._on_show_to_toggled)
        v_splitter.addWidget(self._msg_table)

        self._treemap = TreemapWidget()
        self._treemap.folder_clicked.connect(self._on_treemap_folder_clicked)
        self._treemap.folder_key_clicked.connect(self._on_treemap_folder_key_clicked)
        self._treemap.sender_clicked.connect(self._on_treemap_sender_clicked)
        self._treemap.receiver_clicked.connect(self._on_treemap_receiver_clicked)
        self._treemap.message_clicked.connect(self._on_treemap_message_clicked)
        self._treemap.view_mode_changed.connect(self._on_treemap_view_changed)
        v_splitter.addWidget(self._treemap)

        v_splitter.setSizes([500, 200])
        h_splitter.addWidget(v_splitter)
        h_splitter.setSizes([230, 1050])

        main_layout.addWidget(h_splitter, stretch=1)

    def _build_status_bar(self) -> None:
        self._progress_panel = ProgressPanel()
        self._progress_panel.cancel_clicked.connect(self._on_cancel)
        self._size_label = QLabel("")
        status_bar = QStatusBar()
        status_bar.addWidget(self._progress_panel, stretch=1)
        status_bar.addPermanentWidget(self._size_label)
        self.setStatusBar(status_bar)
        self._quota_usage: int | None = None  # server-reported usage in bytes
        self._quota_bytes: int | None = None  # server quota limit in bytes

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("Add Account…", self._on_add_account)
        file_menu.addAction("Edit Account…", self._on_edit_account)
        file_menu.addAction("Remove Account", self._on_remove_account)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction("Reload from Cache", self._on_reload_cache)
        view_menu.addAction("Settings…", self._on_settings)
        view_menu.addSeparator()
        view_menu.addAction("Show Log", self._show_log_dock)

        actions_menu = menubar.addMenu("&Actions")
        actions_menu.addAction("Scan All Folders", self._on_scan)
        actions_menu.addAction("Scan Selected Folder", self._on_scan_selected)
        actions_menu.addSeparator()
        actions_menu.addAction("Extract Attachments…", self._on_extract_attachments)
        actions_menu.addAction("Detach Attachments…", self._on_detach)
        actions_menu.addSeparator()
        actions_menu.addAction("Backup…", self._on_backup_only)
        actions_menu.addAction("Backup && Delete…", self._on_backup_delete)
        actions_menu.addAction("Delete Selected…", self._on_delete)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("About MailSweep", self._on_about)

    # ── Account management ────────────────────────────────────────────────────

    def _load_accounts(self) -> None:
        self._account_combo.blockSignals(True)
        self._account_combo.clear()
        for acc in self._account_repo.get_all():
            self._account_combo.addItem(acc.display_name, acc)
        self._account_combo.blockSignals(False)
        if self._account_combo.count() > 0:
            self._on_account_changed(0)

    def _on_account_changed(self, idx: int) -> None:
        acc = self._account_combo.itemData(idx)
        if isinstance(acc, Account):
            self._current_account = acc
            self._fetch_folder_list()
            self._fetch_quota()
            self._refresh_folder_panel()
            self._refresh_treemap()
            self._reload_messages()
            self._refresh_size_label()
            self._update_correspondent_column()

    def _fetch_folder_list(self) -> None:
        """Connect to the server and pull the folder list into the DB (no message fetch)."""
        if not self._current_account or not self._current_account.id:
            return
        from mailsweep.imap.connection import IMAPConnectionError, connect, list_folders
        try:
            client = connect(self._current_account)
            folder_names = list_folders(client)
            client.logout()
        except IMAPConnectionError as exc:
            logger.warning("Could not fetch folder list: %s", exc)
            return

        for name in folder_names:
            if not self._folder_repo.get_by_name(self._current_account.id, name):
                f = Folder(account_id=self._current_account.id, name=name)
                self._folder_repo.upsert(f)

    def _on_add_account(self) -> None:
        dlg = AccountDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            account = dlg.get_account()
            saved = self._account_repo.upsert(account)
            self._load_accounts()
            for i in range(self._account_combo.count()):
                a = self._account_combo.itemData(i)
                if isinstance(a, Account) and a.id == saved.id:
                    self._account_combo.setCurrentIndex(i)
                    break

    def _on_edit_account(self) -> None:
        if not self._current_account:
            return
        dlg = AccountDialog(self, self._current_account)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._account_repo.upsert(dlg.get_account())
            self._load_accounts()

    def _on_remove_account(self) -> None:
        if not self._current_account:
            return
        reply = QMessageBox.question(
            self, "Remove Account",
            f"Remove account '{self._current_account.display_name}'?\n"
            "All cached data will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            assert self._current_account.id is not None
            self._account_repo.delete(self._current_account.id)
            self._current_account = None
            self._load_accounts()

    # ── Folder panel ──────────────────────────────────────────────────────────

    def _refresh_folder_panel(self) -> None:
        if not self._current_account:
            return
        assert self._current_account.id is not None
        folders = self._folder_repo.get_by_account(self._current_account.id)
        folder_ids = [f.id for f in folders if f.id is not None]
        dedup_size, dedup_count = self._msg_repo.get_dedup_total_size(folder_ids) if folder_ids else (0, 0)

        # Compute unlabelled stats for Gmail accounts
        unlabelled_stats: tuple[int, int] | None = None
        all_mail = self._folder_repo.find_all_mail_folder(self._current_account.id)
        if all_mail and all_mail.id is not None:
            other_ids = [fid for fid in folder_ids if fid != all_mail.id]
            count, size = self._msg_repo.get_unlabelled_stats(all_mail.id, other_ids)
            unlabelled_stats = (count, size)

        self._folder_panel.populate(folders, dedup_total=dedup_size, unlabelled_stats=unlabelled_stats)

    def _on_folder_selected(self, folder_ids: list[int]) -> None:
        self._current_folder_ids = folder_ids
        self._update_correspondent_column()
        self._reload_messages()
        self._refresh_treemap()

    _SENT_NAMES = {"sent", "sent mail", "sent items"}

    def _is_sent_folder(self, folder_ids: list[int]) -> bool:
        """Return True if ALL selected folders match common Sent folder names."""
        if not folder_ids or not self._current_account:
            return False
        if folder_ids == [UNLABELLED_ID]:
            return False
        for fid in folder_ids:
            folder = self._folder_repo.get_by_id(fid)
            if not folder:
                return False
            # Check the leaf name (last path component) and full name
            name_lower = folder.name.lower()
            leaf = name_lower.rsplit("/", 1)[-1]
            if leaf not in self._SENT_NAMES and name_lower not in self._SENT_NAMES:
                return False
        return True

    def _update_correspondent_column(self) -> None:
        key = tuple(sorted(self._current_folder_ids))
        if key in self._folder_show_to:
            show_to = self._folder_show_to[key]
        else:
            show_to = self._is_sent_folder(self._current_folder_ids)
        self._msg_table.set_show_to(show_to)

    def _on_show_to_toggled(self, show_to: bool) -> None:
        """Remember the user's manual From/To choice for the current folder."""
        key = tuple(sorted(self._current_folder_ids))
        self._folder_show_to[key] = show_to

    # ── Message table ─────────────────────────────────────────────────────────

    def _reload_messages(self) -> None:
        if not self._current_account:
            self._msg_table.clear()
            return
        assert self._current_account.id is not None

        # Virtual "Unlabelled" folder
        if self._current_folder_ids == [UNLABELLED_ID]:
            filter_kwargs = self._filter_bar.get_filter_kwargs()
            messages = self._query_unlabelled(**filter_kwargs)
            self._msg_table.set_messages(messages)
            self._update_status(f"{len(messages)} messages (unlabelled)")
            return

        # Determine folder_ids filter
        if self._current_folder_ids:
            folder_ids = self._current_folder_ids
        else:
            # All folders for this account
            folders = self._folder_repo.get_by_account(self._current_account.id)
            folder_ids = [f.id for f in folders if f.id is not None]

        filter_kwargs = self._filter_bar.get_filter_kwargs()
        messages = self._msg_repo.query_messages(folder_ids=folder_ids, **filter_kwargs)
        self._msg_table.set_messages(messages)
        self._update_status(f"{len(messages)} messages")

    def _on_filter_changed(self, kwargs: dict) -> None:
        self._reload_messages()

    def _on_reload_cache(self) -> None:
        self._reload_messages()

    def _query_unlabelled(self, **filter_kwargs) -> list[Message]:
        """Query messages that exist only in All Mail (no other labels)."""
        if not self._current_account or not self._current_account.id:
            return []
        all_mail = self._folder_repo.find_all_mail_folder(self._current_account.id)
        if not all_mail or all_mail.id is None:
            return []
        folders = self._folder_repo.get_by_account(self._current_account.id)
        other_ids = [f.id for f in folders if f.id is not None and f.id != all_mail.id]
        return self._msg_repo.query_unlabelled_messages(
            all_mail.id, other_ids, **filter_kwargs
        )

    # ── Treemap ───────────────────────────────────────────────────────────────

    def _get_active_folder_ids(self) -> list[int]:
        """Return folder IDs for the current view (selected or all)."""
        if self._current_folder_ids and self._current_folder_ids != [UNLABELLED_ID]:
            return self._current_folder_ids
        if not self._current_account or not self._current_account.id:
            return []
        folders = self._folder_repo.get_by_account(self._current_account.id)
        return [f.id for f in folders if f.id is not None]

    def _refresh_treemap(self) -> None:
        if not self._current_account:
            return
        assert self._current_account.id is not None
        mode = self._treemap.view_mode
        is_unlabelled = self._current_folder_ids == [UNLABELLED_ID]

        if mode == VIEW_FOLDERS:
            if is_unlabelled:
                # No sub-folders to drill into — show top messages by size
                messages = self._query_unlabelled(order_by="size_bytes DESC", limit=200)
                items = [
                    TreemapItem(
                        key=f"msg:{m.uid}",
                        label=m.subject or "(no subject)",
                        sublabel=m.from_addr.split("<")[-1].rstrip(">") if m.from_addr and "<" in m.from_addr else (m.from_addr or ""),
                        size_bytes=m.size_bytes,
                    )
                    for m in messages if m.size_bytes > 0
                ]
            else:
                items = self._treemap_folder_items()

        elif mode == VIEW_SENDERS:
            if is_unlabelled:
                messages = self._query_unlabelled(order_by="size_bytes DESC", limit=5000)
                items = self._aggregate_messages_by_field(messages, "from_addr")
            else:
                folder_ids = self._get_active_folder_ids()
                rows = self._msg_repo.get_sender_summary(folder_ids=folder_ids or None)
                items = [
                    TreemapItem(
                        key=row["sender_email"],
                        label=row["sender_email"],
                        sublabel=f"{row['message_count']} msgs",
                        size_bytes=row["total_size_bytes"],
                    )
                    for row in rows if row["total_size_bytes"] > 0
                ]

        elif mode == VIEW_RECEIVERS:
            if is_unlabelled:
                messages = self._query_unlabelled(order_by="size_bytes DESC", limit=5000)
                items = self._aggregate_messages_by_field(messages, "to_addr")
            else:
                folder_ids = self._get_active_folder_ids()
                rows = self._msg_repo.get_receiver_summary(folder_ids=folder_ids or None)
                items = [
                    TreemapItem(
                        key=row["receiver_email"],
                        label=row["receiver_email"],
                        sublabel=f"{row['message_count']} msgs",
                        size_bytes=row["total_size_bytes"],
                    )
                    for row in rows if row["total_size_bytes"] > 0
                ]

        elif mode == VIEW_MESSAGES:
            if is_unlabelled:
                messages = self._query_unlabelled(order_by="size_bytes DESC", limit=200)
            else:
                folder_ids = self._get_active_folder_ids()
                messages = self._msg_repo.query_messages(
                    folder_ids=folder_ids or None,
                    order_by="size_bytes DESC",
                    limit=200,
                )
            folder_map = self._build_folder_name_map()
            items = [
                TreemapItem(
                    key=str(m.uid),
                    label=m.subject or "(no subject)",
                    sublabel=folder_map.get(m.folder_id, ""),
                    size_bytes=m.size_bytes,
                )
                for m in messages if m.size_bytes > 0
            ]

        else:
            items = []

        self._treemap.set_data(items)

    def _aggregate_messages_by_field(
        self, messages: list[Message], field: str,
    ) -> list[TreemapItem]:
        """Aggregate messages by a sender/receiver field for treemap display."""
        import re
        groups: dict[str, tuple[int, int]] = {}  # email → (count, size)
        for m in messages:
            addr = getattr(m, field) or ""
            # Extract email from "Name <email>" format
            match = re.search(r"<([^>]+)>", addr)
            email = match.group(1).lower() if match else addr.lower()
            count, size = groups.get(email, (0, 0))
            groups[email] = (count + 1, size + m.size_bytes)
        items = [
            TreemapItem(
                key=email,
                label=email,
                sublabel=f"{count} msgs",
                size_bytes=size,
            )
            for email, (count, size) in groups.items() if size > 0
        ]
        items.sort(key=lambda x: x.size_bytes, reverse=True)
        return items

    def _treemap_folder_items(self) -> list[TreemapItem]:
        """Build treemap items for Folders view with drill-down support.

        - No folder selected → show top-level folders (root children)
        - Folder selected with sub-folders → show its direct children
        - Leaf folder selected → show top messages by size
        """
        assert self._current_account and self._current_account.id
        all_folders = self._folder_repo.get_by_account(self._current_account.id)

        if not self._current_folder_ids:
            # Show top-level: group by first path component
            return self._treemap_folder_level(all_folders, prefix="")

        # A specific folder is selected — find it
        selected = self._folder_repo.get_by_id(self._current_folder_ids[0])
        if not selected:
            return self._treemap_folder_level(all_folders, prefix="")

        # Find direct children of this folder
        child_items = self._treemap_folder_level(all_folders, prefix=selected.name + "/")

        if child_items:
            return child_items

        # Leaf folder — show top messages by size
        folder_map = self._build_folder_name_map()
        messages = self._msg_repo.query_messages(
            folder_ids=self._current_folder_ids,
            order_by="size_bytes DESC",
            limit=200,
        )
        # Tag these with "msg:" prefix so click handler knows they're messages
        return [
            TreemapItem(
                key=f"msg:{m.uid}",
                label=m.subject or "(no subject)",
                sublabel=m.from_addr.split("<")[-1].rstrip(">") if "<" in m.from_addr else m.from_addr,
                size_bytes=m.size_bytes,
            )
            for m in messages if m.size_bytes > 0
        ]

    def _treemap_folder_level(
        self, all_folders: list[Folder], prefix: str
    ) -> list[TreemapItem]:
        """Return treemap items for direct children at a given folder path level.

        Groups child folders that are themselves parents into a single tile
        whose size is the sum of all descendants.
        """
        # Collect direct children (one level below prefix)
        children: dict[str, list[Folder]] = {}
        for f in all_folders:
            if not f.name.startswith(prefix):
                continue
            rest = f.name[len(prefix):]
            if not rest:
                continue  # skip the folder itself
            top = rest.split("/")[0]
            children.setdefault(top, []).append(f)

        items: list[TreemapItem] = []
        for child_name, group in children.items():
            full_path = prefix + child_name
            total_size = sum(f.total_size_bytes for f in group)
            total_msgs = sum(f.message_count for f in group)
            if total_size <= 0:
                continue
            # Find the folder ID for this exact path (may be a namespace with no ID)
            exact = next((f for f in group if f.name == full_path), None)
            key = str(exact.id) if exact and exact.id is not None else f"path:{full_path}"
            is_group = len(group) > 1 or (exact is None)
            sublabel = f"{total_msgs:,} msgs" if total_msgs else ""
            if is_group:
                sublabel = f"{len(group)} sub-labels, {sublabel}" if sublabel else f"{len(group)} sub-labels"
            items.append(TreemapItem(
                key=key,
                label=child_name,
                sublabel=sublabel,
                size_bytes=total_size,
            ))
        return items

    def _on_treemap_folder_clicked(self, folder_id: int) -> None:
        """Handle click on a treemap tile that has a real folder_id."""
        self._current_folder_ids = [folder_id]
        self._folder_panel.select_folder(folder_id)
        self._reload_messages()
        self._refresh_treemap()  # drill down into this folder

    def _on_treemap_folder_key_clicked(self, key: str) -> None:
        """Handle clicks on treemap tiles with special keys (path: or msg:)."""
        if key.startswith("msg:"):
            # Message tile in a leaf folder drill-down
            try:
                uid = int(key[4:])
                self._filter_bar.clear_filters()
                self._reload_messages()
                self._msg_table.select_by_uid(uid)
            except ValueError:
                pass
        elif key.startswith("path:"):
            # Namespace folder (e.g. "[Gmail]") — find a child folder to select
            path = key[5:]
            if self._current_account and self._current_account.id:
                all_folders = self._folder_repo.get_by_account(self._current_account.id)
                # Find any child folder to get its ID for selection
                children = [f for f in all_folders
                            if f.name.startswith(path + "/") and f.id is not None]
                if children:
                    # Select the namespace folder by finding its exact entry
                    exact = next((f for f in all_folders if f.name == path and f.id is not None), None)
                    if exact:
                        self._current_folder_ids = [exact.id]
                        self._folder_panel.select_folder(exact.id)
                    else:
                        # No exact folder — use all children as the scope
                        self._current_folder_ids = [f.id for f in children]
                    self._reload_messages()
                    self._refresh_treemap()

    def _on_treemap_sender_clicked(self, from_addr: str) -> None:
        self._filter_bar.set_from_filter(from_addr)
        self._reload_messages()

    def _on_treemap_receiver_clicked(self, to_addr: str) -> None:
        self._filter_bar.set_to_filter(to_addr)
        self._reload_messages()

    def _on_treemap_message_clicked(self, uid: int) -> None:
        # Clear filters so the message is visible in the table, then select it
        self._filter_bar.clear_filters()
        self._reload_messages()
        if not self._msg_table.select_by_uid(uid):
            self._update_status(f"Message UID {uid} not found in current view")

    def _on_treemap_view_changed(self, mode: int) -> None:
        self._refresh_treemap()

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _on_scan(self) -> None:
        """Scan ALL folders on the server."""
        if not self._current_account:
            QMessageBox.information(self, "No Account", "Please add an account first.")
            return
        if self._scan_thread and self._scan_thread.isRunning():
            QMessageBox.information(self, "Busy", "A scan is already in progress.")
            return
        assert self._current_account.id is not None

        from mailsweep.imap.connection import IMAPConnectionError, connect, list_folders
        self._progress_panel.set_running("Connecting…")
        self._scan_btn.setEnabled(False)

        try:
            client = connect(self._current_account)
            folder_names = list_folders(client)
            client.logout()
        except IMAPConnectionError as exc:
            self._progress_panel.set_error(str(exc))
            self._scan_btn.setEnabled(True)
            return

        folders: list[Folder] = []
        for name in folder_names:
            f = self._folder_repo.get_by_name(self._current_account.id, name)
            if not f:
                f = Folder(account_id=self._current_account.id, name=name)
                f = self._folder_repo.upsert(f)
            folders.append(f)

        self._refresh_folder_panel()
        self._start_scan(folders)

    def _on_scan_selected(self) -> None:
        """Scan only the folder(s) currently selected in the folder panel."""
        if not self._current_account:
            QMessageBox.information(self, "No Account", "Please add an account first.")
            return
        if not self._current_folder_ids:
            QMessageBox.information(
                self, "No Folder Selected",
                "Click a folder in the tree first, then click Scan Selected Folder.",
            )
            return
        if self._current_folder_ids == [UNLABELLED_ID]:
            QMessageBox.information(
                self, "Virtual Folder",
                "Unlabelled is a virtual folder. Use 'Scan All' to refresh data.",
            )
            return
        if self._scan_thread and self._scan_thread.isRunning():
            QMessageBox.information(self, "Busy", "A scan is already in progress.")
            return
        assert self._current_account.id is not None

        folders: list[Folder] = []
        for fid in self._current_folder_ids:
            f = self._folder_repo.get_by_id(fid)
            if f:
                folders.append(f)

        if not folders:
            QMessageBox.information(self, "No Folder", "Selected folder not found in database.")
            return

        self._start_scan(folders)

    def _start_scan(self, folders: list[Folder]) -> None:
        """Common scan launcher used by both Scan All and Scan Selected."""
        assert self._current_account is not None
        self._scan_btn.setEnabled(False)
        self._scan_selected_btn.setEnabled(False)

        worker = QtScanWorker(
            account=self._current_account,
            folders=folders,
            folder_repo=self._folder_repo,
            msg_repo=self._msg_repo,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        worker.folder_started.connect(self._on_scan_folder_started)
        worker.message_batch_done.connect(self._on_scan_batch)
        worker.folder_done.connect(self._on_scan_folder_done)
        worker.all_done.connect(self._on_scan_all_done)
        worker.error.connect(self._on_scan_error)

        self._scan_worker = worker
        self._scan_thread = thread
        thread.start()

    def _on_scan_folder_started(self, folder_name: str) -> None:
        self._progress_panel.set_running(f"Scanning {folder_name}…")

    def _on_scan_batch(self, messages: list[Message], done: int, total: int) -> None:
        if messages:
            self._msg_table.append_messages(messages)
        if total > 0:
            self._progress_panel.set_progress(done, total, f"Scanning… {done}/{total}")

    def _on_scan_folder_done(self, folder: Folder) -> None:
        self._folder_panel.update_folder_size(folder.id, folder.total_size_bytes)
        self._refresh_treemap()
        self._refresh_size_label()

    def _on_scan_all_done(self) -> None:
        self._progress_panel.set_done("Scan complete")
        self._scan_btn.setEnabled(True)
        self._scan_selected_btn.setEnabled(True)
        self._scan_worker = None
        self._scan_thread = None
        self._reload_messages()
        self._refresh_treemap()

    def _on_scan_error(self, msg: str) -> None:
        self._progress_panel.set_error(msg)
        logger.error("Scan error: %s", msg)

    def _on_cancel(self) -> None:
        if self._scan_worker:
            self._scan_worker.cancel()
            self._progress_panel.set_running("Cancelling…")

    # ── Destructive operations ─────────────────────────────────────────────────

    def _get_operation_messages(self) -> list[Message]:
        """Return checked messages, or selected if none checked."""
        checked = self._msg_table.get_checked_messages()
        if checked:
            return checked
        selected = self._msg_table.get_selected_messages()
        return selected

    def _build_folder_name_map(self) -> dict[int, str]:
        if not self._current_account or not self._current_account.id:
            return {}
        folders = self._folder_repo.get_by_account(self._current_account.id)
        return {f.id: f.name for f in folders if f.id is not None}

    def _on_extract_messages(self, messages: list[Message]) -> None:
        """Context menu handler for extract attachments."""
        self._on_extract_attachments(messages)

    def _on_extract_attachments(self, messages: list[Message] | None = None) -> None:
        """Extract/save attachments locally without modifying messages on the server."""
        if messages is None:
            messages = self._get_operation_messages()
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return
        with_att = [m for m in messages if m.has_attachment]
        if not with_att:
            QMessageBox.information(self, "No Attachments", "Selected messages have no attachments.")
            return

        reply = QMessageBox.information(
            self, "Extract Attachments",
            f"Extract attachments from {len(with_att)} message(s)?\n"
            f"Attachments will be saved to:\n{cfg.DEFAULT_SAVE_DIR}\n\n"
            "Messages on the server will NOT be modified.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return

        assert self._current_account is not None
        from mailsweep.workers.detach_worker import DetachWorker

        worker = DetachWorker(
            account=self._current_account,
            messages=with_att,
            save_dir=cfg.DEFAULT_SAVE_DIR,
            folder_id_to_name=self._build_folder_name_map(),
            detach_from_server=False,
        )
        self._run_worker(worker, "Extracting attachments…")

    def _on_detach(self) -> None:
        self._on_detach_messages(self._get_operation_messages())

    def _on_detach_messages(self, messages: list[Message]) -> None:
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return
        with_att = [m for m in messages if m.has_attachment]
        if not with_att:
            QMessageBox.information(self, "No Attachments", "Selected messages have no attachments.")
            return

        reply = QMessageBox.warning(
            self, "Detach Attachments",
            f"Detach attachments from {len(with_att)} message(s)?\n"
            f"Attachments will be saved to:\n{cfg.DEFAULT_SAVE_DIR}\n\n"
            "The original messages on the server will be replaced with stripped versions.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        assert self._current_account is not None
        from mailsweep.workers.detach_worker import DetachWorker

        worker = DetachWorker(
            account=self._current_account,
            messages=with_att,
            save_dir=cfg.DEFAULT_SAVE_DIR,
            folder_id_to_name=self._build_folder_name_map(),
        )
        self._run_worker(worker, "Detaching attachments…", needs_rescan=True, updates_cache=True)

    def _on_backup_messages_only(self, messages: list[Message]) -> None:
        """Context menu handler for backup without delete."""
        self._on_backup_only(messages)

    def _on_backup_only(self, messages: list[Message] | None = None) -> None:
        """Backup selected messages to .eml files without deleting from server."""
        if messages is None:
            messages = self._get_operation_messages()
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return

        reply = QMessageBox.information(
            self, "Backup",
            f"Backup {len(messages)} message(s) to .eml files?\n"
            f"Backup directory:\n{cfg.DEFAULT_SAVE_DIR / 'backups'}\n\n"
            "Messages on the server will NOT be deleted.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return

        assert self._current_account is not None
        from mailsweep.workers.backup_worker import BackupWorker

        worker = BackupWorker(
            account=self._current_account,
            messages=messages,
            backup_dir=cfg.DEFAULT_SAVE_DIR / "backups",
            folder_id_to_name=self._build_folder_name_map(),
            delete_after=False,
        )
        self._run_worker(worker, "Backing up messages…")

    def _on_backup_delete(self) -> None:
        self._on_backup_messages(self._get_operation_messages())

    def _on_backup_messages(self, messages: list[Message]) -> None:
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return

        reply = QMessageBox.warning(
            self, "Backup & Delete",
            f"Backup {len(messages)} message(s) to .eml files and DELETE from server?\n"
            f"Backup directory:\n{cfg.DEFAULT_SAVE_DIR / 'backups'}\n\n"
            "This operation is IRREVERSIBLE on the server.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        assert self._current_account is not None
        from mailsweep.workers.backup_worker import BackupWorker

        worker = BackupWorker(
            account=self._current_account,
            messages=messages,
            backup_dir=cfg.DEFAULT_SAVE_DIR / "backups",
            folder_id_to_name=self._build_folder_name_map(),
        )
        self._run_worker(worker, "Backing up and deleting…", updates_cache=True)

    def _on_delete(self) -> None:
        self._on_delete_messages(self._get_operation_messages())

    def _on_delete_messages(self, messages: list[Message]) -> None:
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return

        from mailsweep.imap.connection import find_trash_folder
        folder_map = self._build_folder_name_map()
        trash_folder = find_trash_folder(folder_map)
        if trash_folder:
            detail = f"Messages will be moved to {trash_folder}."
        else:
            detail = "Messages will be permanently deleted (no Trash folder found)."

        reply = QMessageBox.warning(
            self, "Delete Messages",
            f"Delete {len(messages)} message(s)?\n\n{detail}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        assert self._current_account is not None
        from mailsweep.workers.delete_worker import DeleteWorker

        worker = DeleteWorker(
            account=self._current_account,
            messages=messages,
            folder_id_to_name=folder_map,
        )
        self._run_worker(worker, f"Deleting {len(messages)} messages…", updates_cache=True)

    def _run_worker(
        self, worker, status_msg: str, *,
        needs_rescan: bool = False, updates_cache: bool = False,
    ) -> None:
        """Wire a generic QObject worker to a QThread and start it."""
        self._op_processed = {}
        self._op_needs_rescan = needs_rescan
        self._op_updates_cache = updates_cache
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        if hasattr(worker, "progress"):
            worker.progress.connect(
                lambda done, total, msg: self._progress_panel.set_progress(done, total, msg)
                if not self._is_closing else None
            )
        if hasattr(worker, "error"):
            worker.error.connect(self._on_scan_error)
        if hasattr(worker, "message_done"):
            worker.message_done.connect(self._on_op_message_done)
        if hasattr(worker, "finished"):
            worker.finished.connect(self._on_op_finished)

        # Keep references to prevent garbage collection before thread runs
        self._op_worker = worker
        self._op_thread = thread

        def _cleanup():
            self._op_worker = None
            self._op_thread = None
        thread.finished.connect(_cleanup)

        self._progress_panel.set_running(status_msg)
        thread.start()

    def _on_op_message_done(self, msg, result) -> None:
        if self._op_updates_cache:
            self._op_processed.setdefault(msg.folder_id, []).append(msg.uid)
        logger.info("Operation done for message uid=%s: %s", msg.uid, result)

    def _on_op_finished(self) -> None:
        if self._is_closing:
            return
        self._progress_panel.set_done("Operation complete")

        # Remove processed UIDs from cache and recompute folder stats
        affected_folder_ids = list(self._op_processed.keys())
        if self._op_updates_cache and affected_folder_ids:
            for folder_id, uids in self._op_processed.items():
                self._msg_repo.delete_uids(folder_id, uids)
                self._folder_repo.update_stats(folder_id)
        self._op_processed = {}

        if self._op_needs_rescan and affected_folder_ids:
            # Detach APPENDs replacement messages — rescan to pick up new UIDs
            folders = [
                f for fid in affected_folder_ids
                if (f := self._folder_repo.get_by_id(fid)) is not None
            ]
            if folders:
                self._start_scan(folders)
                return  # _on_scan_all_done will refresh UI

        self._reload_messages()
        self._refresh_folder_panel()
        self._refresh_treemap()
        self._refresh_size_label()

    # ── View Headers ──────────────────────────────────────────────────────────

    def _on_view_headers(self, msg: Message) -> None:
        from PyQt6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Headers — {msg.subject}")
        dlg.resize(600, 400)
        layout = QVBoxLayout(dlg)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            f"UID: {msg.uid}\n"
            f"Folder: {msg.folder_name}\n"
            f"From: {msg.from_addr}\n"
            f"To: {msg.to_addr}\n"
            f"Subject: {msg.subject}\n"
            f"Date: {msg.date}\n"
            f"Size: {human_size(msg.size_bytes)}\n"
            f"Has Attachment: {msg.has_attachment}\n"
            f"Attachment Names: {', '.join(msg.attachment_names)}\n"
            f"Flags: {', '.join(msg.flags)}\n"
        )
        layout.addWidget(text)
        dlg.exec()

    def _build_log_dock(self) -> None:
        from mailsweep.ui.log_dock import LogDockWidget
        self._log_dock = LogDockWidget(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.hide()

    def _show_log_dock(self) -> None:
        self._log_dock.show()

    def _on_settings(self) -> None:
        from mailsweep.ui.settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    def _update_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 3000)

    def _refresh_size_label(self) -> None:
        """Update the persistent total-size / quota label in the status bar.

        Shows: Google storage quota (includes Drive+Photos) | Mailbox dedup size
        """
        if not self._current_account or not self._current_account.id:
            self._size_label.setText("")
            return

        hs = lambda b: human_size(b, decimals=2)
        parts: list[str] = []

        # Google/IMAP quota (total account storage including Drive, Photos)
        if self._quota_usage is not None and self._quota_bytes and self._quota_bytes > 0:
            pct = self._quota_usage / self._quota_bytes * 100
            parts.append(f"Google: {hs(self._quota_usage)} / {hs(self._quota_bytes)} ({pct:.2f}%)")

        # Deduplicated mailbox size (avoids Gmail label double-counting)
        folders = self._folder_repo.get_by_account(self._current_account.id)
        folder_ids = [f.id for f in folders if f.id is not None]
        if folder_ids:
            dedup_size, dedup_count = self._msg_repo.get_dedup_total_size(folder_ids)
            if dedup_size > 0:
                parts.append(f"Mail: {hs(dedup_size)} ({dedup_count:,} msgs)")

        self._size_label.setText("  " + "  |  ".join(parts) + "  " if parts else "")

    def _fetch_quota(self) -> None:
        """Try to get IMAP QUOTA and store the limit in bytes."""
        if not self._current_account:
            return
        from mailsweep.imap.connection import IMAPConnectionError, connect
        try:
            client = connect(self._current_account)
            # get_quota_root returns (MailboxQuotaRoots, [Quota, ...])
            # Quota is typically a namedtuple-like with quota_root, resource, usage, limit
            result = client.get_quota_root("INBOX")
            if result and len(result) >= 2:
                quotas = result[1]  # list of Quota objects
                for q in quotas:
                    # q might be a tuple (root, resource, usage, limit) or have named attrs
                    if hasattr(q, "resource") and hasattr(q, "limit"):
                        if q.resource.upper() == "STORAGE":
                            self._quota_usage = q.usage * 1024  # STORAGE is in KB
                            self._quota_bytes = q.limit * 1024
                            break
                    elif isinstance(q, (list, tuple)) and len(q) >= 4:
                        resource = q[1] if isinstance(q[1], str) else str(q[1])
                        if resource.upper() == "STORAGE":
                            self._quota_usage = int(q[2]) * 1024
                            self._quota_bytes = int(q[3]) * 1024
                            break
            client.logout()
        except Exception as exc:
            logger.debug("Could not fetch quota: %s", exc)
            self._quota_bytes = None

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About MailSweep",
            "MailSweep — IMAP Mailbox Analyzer & Cleaner\n\n"
            "Visualize where your email storage is going and\n"
            "surgically reclaim it with bulk operations.\n\n"
            "Built with Python, PyQt6, and imapclient.",
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._is_closing = True
        if self._scan_worker:
            self._scan_worker.cancel()
        self._conn.close()
        super().closeEvent(event)
