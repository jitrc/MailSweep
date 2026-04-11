"""Blocklist Manager dialog."""
from __future__ import annotations
import datetime
import os
from pathlib import Path

import mailsweep.config as cfg
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from mailsweep.workers.blocklist_worker import BlocklistSyncWorker


class BlocklistDialog(QDialog):
    def __init__(self, blocklist_repo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repo = blocklist_repo
        self.setWindowTitle("Blocklist Manager")
        self.resize(560, 560)
        self._build_ui()
        self._refresh_local_table()
        self._refresh_community_tab()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_local_tab(), "Local")
        self._tabs.addTab(self._build_community_tab(), "Community")
        layout.addWidget(self._tabs, stretch=1)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

    def _build_local_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel("Entries are matched against every scanned message's From address.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._local_table = QTableWidget(0, 2)
        self._local_table.setHorizontalHeaderLabels(["Pattern", "Added"])
        self._local_table.horizontalHeader().setStretchLastSection(True)
        self._local_table.setColumnWidth(0, 280)
        self._local_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._local_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._local_table.itemDoubleClicked.connect(self._on_local_double_click)
        layout.addWidget(self._local_table, stretch=1)

        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("email@example.com  or  @domain.com")
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._on_add)
        self._add_input.returnPressed.connect(self._on_add)
        add_row.addWidget(self._add_input, stretch=1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        btn_row = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._on_local_remove)
        export_btn = QPushButton("Export to File…")
        export_btn.clicked.connect(self._on_export)
        import_btn = QPushButton("Import from File…")
        import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(import_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    def _build_community_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Enable/disable toggle
        self._community_enabled_cb = QCheckBox("Enable community blocklist")
        self._community_enabled_cb.setChecked(cfg.BLOCKLIST_USE_COMMUNITY)
        self._community_enabled_cb.toggled.connect(self._on_community_toggle)
        layout.addWidget(self._community_enabled_cb)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL:"))
        self._url_input = QLineEdit()
        self._url_input.setText(cfg.BLOCKLIST_COMMUNITY_URL)
        self._url_input.setPlaceholderText("https://raw.githubusercontent.com/…/blocklist.txt")
        url_save_btn = QPushButton("Save URL")
        url_save_btn.clicked.connect(self._on_save_url)
        url_row.addWidget(self._url_input, stretch=1)
        url_row.addWidget(url_save_btn)
        layout.addLayout(url_row)

        self._community_status = QLabel()
        self._community_status.setWordWrap(True)
        layout.addWidget(self._community_status)

        # Editable table for community entries
        self._community_table = QTableWidget(0, 1)
        self._community_table.setHorizontalHeaderLabels(["Pattern"])
        self._community_table.horizontalHeader().setStretchLastSection(True)
        self._community_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._community_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        layout.addWidget(self._community_table, stretch=1)

        add_row = QHBoxLayout()
        self._community_add_input = QLineEdit()
        self._community_add_input.setPlaceholderText("email@example.com  or  @domain.com")
        comm_add_btn = QPushButton("Add")
        comm_add_btn.clicked.connect(self._on_community_add)
        self._community_add_input.returnPressed.connect(self._on_community_add)
        add_row.addWidget(self._community_add_input, stretch=1)
        add_row.addWidget(comm_add_btn)
        layout.addLayout(add_row)

        btn_row = QHBoxLayout()
        comm_remove_btn = QPushButton("Remove Selected")
        comm_remove_btn.clicked.connect(self._on_community_remove)
        self._sync_btn = QPushButton("Sync from URL")
        self._sync_btn.clicked.connect(self._on_sync)
        self._sync_btn.setEnabled(bool(cfg.BLOCKLIST_COMMUNITY_URL.strip()))
        comm_save_btn = QPushButton("Save Changes")
        comm_save_btn.clicked.connect(self._on_community_save)
        btn_row.addWidget(comm_remove_btn)
        btn_row.addWidget(self._sync_btn)
        btn_row.addWidget(comm_save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    # ── Local tab logic ────────────────────────────────────────────────────────

    def _refresh_local_table(self) -> None:
        entries = self._repo.get_all()
        self._local_table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            self._local_table.setItem(i, 0, QTableWidgetItem(e["pattern"]))
            self._local_table.setItem(i, 1, QTableWidgetItem(e["added_at"][:16]))

    def _on_add(self) -> None:
        pattern = self._add_input.text().strip().lower()
        if not pattern:
            return
        self._repo.add(pattern)
        self._add_input.clear()
        self._refresh_local_table()

    def _on_local_double_click(self, item: QTableWidgetItem) -> None:
        row = item.row()
        pattern_item = self._local_table.item(row, 0)
        if not pattern_item:
            return
        old_pattern = pattern_item.text()
        self._add_input.setText(old_pattern)
        self._repo.remove(old_pattern)
        self._refresh_local_table()
        self._add_input.setFocus()

    def _on_local_remove(self) -> None:
        rows = {idx.row() for idx in self._local_table.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            pattern = self._local_table.item(row, 0).text()
            self._repo.remove(pattern)
        self._refresh_local_table()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Blocklist",
            str(Path.home() / "blocklist.txt"),
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        entries = self._repo.get_all()
        lines = [
            "# MailSweep Blocklist",
            "# Format: exact email (spam@example.com) or whole domain (@example.com)",
            "# Lines starting with # are comments.",
            "",
        ] + [e["pattern"] for e in entries]
        try:
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
            QMessageBox.information(self, "Export Complete", f"Exported {len(entries)} entries to:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Blocklist",
            str(Path.home()),
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            patterns = [l.strip().lower() for l in lines if l.strip() and not l.strip().startswith("#")]
            for p in patterns:
                self._repo.add(p)
            self._refresh_local_table()
            QMessageBox.information(self, "Import Complete", f"Imported {len(patterns)} entries.")
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))

    # ── Community tab logic ────────────────────────────────────────────────────

    def _refresh_community_tab(self) -> None:
        path = cfg.COMMUNITY_BLOCKLIST_PATH
        if not path.exists():
            self._community_status.setText(
                f"Not synced yet.  URL: {cfg.BLOCKLIST_COMMUNITY_URL or '(not set in Settings)'}"
            )
            self._community_table.setRowCount(0)
            return

        try:
            raw = path.read_text(encoding="utf-8")
            lines = raw.splitlines()
            patterns = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
            count = len(patterns)
            mtime = os.path.getmtime(path)
            dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            self._community_status.setText(f"{count} entries  ·  last synced {dt}")

            self._community_table.setRowCount(count)
            for i, p in enumerate(patterns):
                self._community_table.setItem(i, 0, QTableWidgetItem(p))
        except Exception as exc:
            self._community_status.setText(f"Could not read community file: {exc}")

    def _on_save_url(self) -> None:
        url = self._url_input.text().strip()
        cfg.BLOCKLIST_COMMUNITY_URL = url
        cfg.save_settings()
        self._sync_btn.setEnabled(bool(url))

    def _on_community_toggle(self, checked: bool) -> None:
        cfg.BLOCKLIST_USE_COMMUNITY = checked
        cfg.save_settings()

    def _on_community_add(self) -> None:
        pattern = self._community_add_input.text().strip().lower()
        if not pattern:
            return
        row = self._community_table.rowCount()
        self._community_table.insertRow(row)
        self._community_table.setItem(row, 0, QTableWidgetItem(pattern))
        self._community_add_input.clear()

    def _on_community_remove(self) -> None:
        rows = {idx.row() for idx in self._community_table.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            self._community_table.removeRow(row)

    def _on_community_save(self) -> None:
        """Write the current community table contents back to the community file."""
        patterns = []
        for i in range(self._community_table.rowCount()):
            item = self._community_table.item(i, 0)
            if item and item.text().strip():
                patterns.append(item.text().strip().lower())

        lines = [
            "# MailSweep Community Blocklist",
            "# Format: exact email (spam@example.com) or whole domain (@example.com)",
            "# Lines starting with # are comments.",
            "",
        ] + patterns

        try:
            cfg.COMMUNITY_BLOCKLIST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._refresh_community_tab()
            QMessageBox.information(self, "Saved", f"Saved {len(patterns)} entries to community blocklist.")
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))

    def _on_sync(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Set a community blocklist URL in Settings first.")
            return
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("Syncing…")
        self._thread = QThread()
        self._worker = BlocklistSyncWorker(url, cfg.COMMUNITY_BLOCKLIST_PATH)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_sync_done)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_sync_done(self, count: int, error: str) -> None:
        self._sync_btn.setEnabled(True)
        self._sync_btn.setText("Sync from URL")
        if error:
            QMessageBox.warning(self, "Sync Failed", error)
        else:
            QMessageBox.information(self, "Sync Complete", f"Synced {count} entries.")
        self._refresh_community_tab()
