"""Sender Panel — inline sender list for the left sidebar."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLineEdit,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mailsweep.utils.size_fmt import human_size


class _NumericItem(QTableWidgetItem):
    def __init__(self, display: str, sort_key: float) -> None:
        super().__init__(display)
        self._sort_key = sort_key

    def __lt__(self, other: "QTableWidgetItem") -> bool:
        if isinstance(other, _NumericItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


class SenderPanel(QWidget):
    """Sidebar sender list. Emits sender_selected with selected email addresses."""

    sender_selected = pyqtSignal(list)                  # list[str] of email addresses
    delete_requested = pyqtSignal(list)                 # list[str]
    block_delete_requested = pyqtSignal(list)           # list[str]
    backup_delete_requested = pyqtSignal(list)          # list[str]
    perm_delete_requested = pyqtSignal(list)            # list[str]
    block_perm_delete_requested = pyqtSignal(list)      # list[str]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter senders…")
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Email", "Msgs", "Size"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 140)
        self._table.setColumnWidth(1, 45)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        self._all_rows: list[dict] = []

    def populate(self, rows: list[dict]) -> None:
        self._all_rows = rows
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        filtered = [
            r for r in self._all_rows
            if not text
            or text in (r.get("sender_email") or "").lower()
            or text in (r.get("from_addr") or "").lower()
        ]
        self._populate_table(filtered)

    def _populate_table(self, rows: list[dict]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            email = row.get("sender_email", "") or ""
            count = row.get("message_count", 0)
            size = row.get("total_size_bytes", 0)

            name_item = QTableWidgetItem(email)
            name_item.setData(Qt.ItemDataRole.UserRole, email)

            count_item = QTableWidgetItem()
            count_item.setData(Qt.ItemDataRole.DisplayRole, count)

            size_item = _NumericItem(human_size(size), size)

            self._table.setItem(i, 0, name_item)
            self._table.setItem(i, 1, count_item)
            self._table.setItem(i, 2, size_item)

        self._table.setSortingEnabled(True)
        self._table.sortByColumn(1, Qt.SortOrder.DescendingOrder)

    def _on_selection_changed(self) -> None:
        seen: set[int] = set()
        emails: list[str] = []
        for idx in self._table.selectedIndexes():
            row = idx.row()
            if row in seen:
                continue
            seen.add(row)
            item = self._table.item(row, 0)
            if item:
                email = item.data(Qt.ItemDataRole.UserRole)
                if email:
                    emails.append(email)
        if emails:
            self.sender_selected.emit(emails)

    def _selected_emails(self) -> list[str]:
        seen: set[int] = set()
        emails: list[str] = []
        for idx in self._table.selectedIndexes():
            row = idx.row()
            if row in seen:
                continue
            seen.add(row)
            item = self._table.item(row, 0)
            if item:
                email = item.data(Qt.ItemDataRole.UserRole)
                if email:
                    emails.append(email)
        return emails

    def _on_context_menu(self, pos) -> None:
        emails = self._selected_emails()
        if not emails:
            return
        n = len(emails)
        label = f"{n} sender(s)" if n > 1 else emails[0]
        menu = QMenu(self)
        menu.addAction(f"Delete All From {label}", lambda: self.delete_requested.emit(emails))
        menu.addAction(f"Block && Delete All From {label}", lambda: self.block_delete_requested.emit(emails))
        menu.addAction(f"Backup && Delete All From {label}", lambda: self.backup_delete_requested.emit(emails))
        menu.addSeparator()
        menu.addAction(f"Permanent Delete All From {label}", lambda: self.perm_delete_requested.emit(emails))
        menu.addAction(f"Block && Permanent Delete All From {label}", lambda: self.block_perm_delete_requested.emit(emails))
        menu.exec(self._table.viewport().mapToGlobal(pos))
