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

from mailsweep.config import DB_PATH, DEFAULT_SAVE_DIR
from mailsweep.db.repository import AccountRepository, FolderRepository, MessageRepository
from mailsweep.db.schema import init_db
from mailsweep.models.account import Account
from mailsweep.models.folder import Folder
from mailsweep.models.message import Message
from mailsweep.ui.account_dialog import AccountDialog
from mailsweep.ui.filter_bar import FilterBar
from mailsweep.ui.folder_panel import FolderPanel
from mailsweep.ui.message_table import MessageTableView
from mailsweep.ui.progress_panel import ProgressPanel
from mailsweep.ui.treemap_widget import TreemapItem, TreemapWidget
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

        self._build_ui()
        self._load_accounts()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_central_widget()
        self._build_status_bar()
        self._build_menu()

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

        self._scan_btn = QPushButton("Scan Mailbox")
        self._scan_btn.clicked.connect(self._on_scan)
        tb.addWidget(self._scan_btn)

        self._detach_btn = QPushButton("Detach Attachments…")
        self._detach_btn.clicked.connect(self._on_detach)
        tb.addWidget(self._detach_btn)

        self._backup_btn = QPushButton("Backup && Delete…")
        self._backup_btn.clicked.connect(self._on_backup_delete)
        tb.addWidget(self._backup_btn)

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
        self._msg_table.detach_requested.connect(self._on_detach_messages)
        self._msg_table.backup_requested.connect(self._on_backup_messages)
        self._msg_table.delete_requested.connect(self._on_delete_messages)
        self._msg_table.view_headers_requested.connect(self._on_view_headers)
        v_splitter.addWidget(self._msg_table)

        self._treemap = TreemapWidget()
        self._treemap.folder_clicked.connect(self._on_treemap_folder_clicked)
        v_splitter.addWidget(self._treemap)

        v_splitter.setSizes([500, 200])
        h_splitter.addWidget(v_splitter)
        h_splitter.setSizes([230, 1050])

        main_layout.addWidget(h_splitter, stretch=1)

    def _build_status_bar(self) -> None:
        self._progress_panel = ProgressPanel()
        self._progress_panel.cancel_clicked.connect(self._on_cancel)
        status_bar = QStatusBar()
        status_bar.addPermanentWidget(self._progress_panel, stretch=1)
        self.setStatusBar(status_bar)

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

        actions_menu = menubar.addMenu("&Actions")
        actions_menu.addAction("Scan Mailbox", self._on_scan)
        actions_menu.addAction("Detach Attachments…", self._on_detach)
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
            self._refresh_folder_panel()
            self._refresh_treemap()
            self._reload_messages()

    def _on_add_account(self) -> None:
        dlg = AccountDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            account = dlg.get_account()
            saved = self._account_repo.upsert(account)
            self._load_accounts()
            # Select new account
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
        self._folder_panel.populate(folders)

    def _on_folder_selected(self, folder_ids: list[int]) -> None:
        self._current_folder_ids = folder_ids
        self._reload_messages()

    # ── Message table ─────────────────────────────────────────────────────────

    def _reload_messages(self) -> None:
        if not self._current_account:
            self._msg_table.clear()
            return
        assert self._current_account.id is not None

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

    # ── Treemap ───────────────────────────────────────────────────────────────

    def _refresh_treemap(self) -> None:
        if not self._current_account:
            return
        assert self._current_account.id is not None
        folders = self._folder_repo.get_by_account(self._current_account.id)
        items = [
            TreemapItem(
                folder_id=f.id,
                folder_name=f.name,
                size_bytes=f.total_size_bytes,
            )
            for f in folders if f.id is not None and f.total_size_bytes > 0
        ]
        self._treemap.set_data(items)

    def _on_treemap_folder_clicked(self, folder_id: int) -> None:
        self._current_folder_ids = [folder_id]
        self._reload_messages()

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _on_scan(self) -> None:
        if not self._current_account:
            QMessageBox.information(self, "No Account", "Please add an account first.")
            return
        if self._scan_thread and self._scan_thread.isRunning():
            QMessageBox.information(self, "Busy", "A scan is already in progress.")
            return
        assert self._current_account.id is not None

        # Get or create folder records
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

    def _on_scan_all_done(self) -> None:
        self._progress_panel.set_done("Scan complete")
        self._scan_btn.setEnabled(True)
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
            f"Attachments will be saved to:\n{DEFAULT_SAVE_DIR}\n\n"
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
            save_dir=DEFAULT_SAVE_DIR,
            folder_id_to_name=self._build_folder_name_map(),
        )
        self._run_worker(worker, "Detaching attachments…")

    def _on_backup_delete(self) -> None:
        self._on_backup_messages(self._get_operation_messages())

    def _on_backup_messages(self, messages: list[Message]) -> None:
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return

        reply = QMessageBox.warning(
            self, "Backup & Delete",
            f"Backup {len(messages)} message(s) to .eml files and DELETE from server?\n"
            f"Backup directory:\n{DEFAULT_SAVE_DIR}\n\n"
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
            backup_dir=DEFAULT_SAVE_DIR / "backups",
            folder_id_to_name=self._build_folder_name_map(),
        )
        self._run_worker(worker, "Backing up and deleting…")

    def _on_delete(self) -> None:
        self._on_delete_messages(self._get_operation_messages())

    def _on_delete_messages(self, messages: list[Message]) -> None:
        if not messages:
            QMessageBox.information(self, "No Selection", "Select messages first.")
            return

        reply = QMessageBox.warning(
            self, "Delete Messages",
            f"Permanently delete {len(messages)} message(s) from the server?\n\n"
            "This operation is IRREVERSIBLE.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        assert self._current_account is not None
        self._progress_panel.set_running(f"Deleting {len(messages)} messages…")

        # Simple in-thread delete (fast, no body fetch needed)
        from collections import defaultdict
        from mailsweep.imap.connection import connect

        try:
            client = connect(self._current_account)
            by_folder: dict[int, list[Message]] = defaultdict(list)
            for msg in messages:
                by_folder[msg.folder_id].append(msg)

            folder_map = self._build_folder_name_map()
            for folder_id, folder_msgs in by_folder.items():
                folder_name = folder_map.get(folder_id, "")
                if not folder_name:
                    continue
                client.select_folder(folder_name)
                uids = [m.uid for m in folder_msgs]
                client.set_flags(uids, [b"\\Deleted"])
                try:
                    client.uid_expunge(uids)
                except Exception:
                    client.expunge()
                self._msg_repo.delete_uids(folder_id, uids)
                self._folder_repo.update_stats(folder_id)

            client.logout()
            self._progress_panel.set_done(f"Deleted {len(messages)} messages")
            self._reload_messages()
            self._refresh_folder_panel()
            self._refresh_treemap()
        except Exception as exc:
            self._progress_panel.set_error(str(exc))
            logger.error("Delete error: %s", exc)

    def _run_worker(self, worker, status_msg: str) -> None:
        """Wire a generic QObject worker to a QThread and start it."""
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        if hasattr(worker, "progress"):
            worker.progress.connect(
                lambda done, total, msg: self._progress_panel.set_progress(done, total, msg)
            )
        if hasattr(worker, "error"):
            worker.error.connect(self._on_scan_error)
        if hasattr(worker, "message_done"):
            worker.message_done.connect(self._on_op_message_done)
        if hasattr(worker, "finished"):
            worker.finished.connect(self._on_op_finished)

        self._progress_panel.set_running(status_msg)
        thread.start()

    def _on_op_message_done(self, msg, result) -> None:
        logger.info("Operation done for message uid=%s: %s", msg.uid, result)

    def _on_op_finished(self) -> None:
        self._progress_panel.set_done("Operation complete")
        self._reload_messages()
        self._refresh_folder_panel()
        self._refresh_treemap()

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
            f"Subject: {msg.subject}\n"
            f"Date: {msg.date}\n"
            f"Size: {human_size(msg.size_bytes)}\n"
            f"Has Attachment: {msg.has_attachment}\n"
            f"Attachment Names: {', '.join(msg.attachment_names)}\n"
            f"Flags: {', '.join(msg.flags)}\n"
        )
        layout.addWidget(text)
        dlg.exec()

    def _update_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 3000)

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
        if self._scan_worker:
            self._scan_worker.cancel()
        self._conn.close()
        super().closeEvent(event)
