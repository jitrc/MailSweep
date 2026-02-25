"""Message table — QTableView + MessageTableModel + QSortFilterProxyModel."""
from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableView,
    QWidget,
)

from mailsweep.models.message import Message
from mailsweep.utils.size_fmt import human_size

COLUMNS = ["", "From", "Subject", "Date", "Size", "Folder", "Attachments"]
COL_CHECK = 0
COL_FROM = 1
COL_SUBJECT = 2
COL_DATE = 3
COL_SIZE = 4
COL_FOLDER = 5
COL_ATTACHMENTS = 6


class MessageTableModel(QAbstractTableModel):
    """Model that holds a flat list of Message objects."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._messages: list[Message] = []
        self._checked: set[int] = set()  # indices

    # ── QAbstractTableModel interface ─────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._messages)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row >= len(self._messages):
            return None
        msg = self._messages[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_data(msg, col)

        if role == Qt.ItemDataRole.CheckStateRole and col == COL_CHECK:
            return Qt.CheckState.Checked if row in self._checked else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.UserRole:
            return msg

        if role == Qt.ItemDataRole.ForegroundRole and col == COL_SIZE:
            size = msg.size_bytes
            if size > 10_000_000:
                return QColor(200, 50, 50)
            if size > 1_000_000:
                return QColor(200, 130, 30)

        if role == Qt.ItemDataRole.FontRole and col == COL_ATTACHMENTS and msg.has_attachment:
            font = QFont()
            font.setBold(True)
            return font

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == COL_CHECK:
            row = index.row()
            if value == Qt.CheckState.Checked:
                self._checked.add(row)
            else:
                self._checked.discard(row)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_messages(self, messages: list[Message]) -> None:
        self.beginResetModel()
        self._messages = list(messages)
        self._checked.clear()
        self.endResetModel()

    def append_messages(self, messages: list[Message]) -> None:
        if not messages:
            return
        start = len(self._messages)
        self.beginInsertRows(QModelIndex(), start, start + len(messages) - 1)
        self._messages.extend(messages)
        self.endInsertRows()

    def get_checked_messages(self) -> list[Message]:
        return [self._messages[i] for i in sorted(self._checked) if i < len(self._messages)]

    def get_selected_messages(self, proxy_indices: list[QModelIndex]) -> list[Message]:
        messages = []
        for pi in proxy_indices:
            msg = pi.data(Qt.ItemDataRole.UserRole)
            if isinstance(msg, Message):
                messages.append(msg)
        return messages

    def check_all(self) -> None:
        self._checked = set(range(len(self._messages)))
        self.dataChanged.emit(
            self.index(0, COL_CHECK),
            self.index(len(self._messages) - 1, COL_CHECK),
            [Qt.ItemDataRole.CheckStateRole],
        )

    def check_none(self) -> None:
        self._checked.clear()
        self.dataChanged.emit(
            self.index(0, COL_CHECK),
            self.index(len(self._messages) - 1, COL_CHECK),
            [Qt.ItemDataRole.CheckStateRole],
        )

    def clear(self) -> None:
        self.set_messages([])

    @property
    def messages(self) -> list[Message]:
        return self._messages

    # ── Private ────────────────────────────────────────────────────────────────

    def _display_data(self, msg: Message, col: int) -> str:
        match col:
            case 0:
                return ""
            case 1:
                return msg.from_addr or ""
            case 2:
                return msg.subject or ""
            case 3:
                return msg.date.strftime("%Y-%m-%d") if msg.date else ""
            case 4:
                return human_size(msg.size_bytes)
            case 5:
                return msg.folder_name or ""
            case 6:
                if msg.has_attachment:
                    names = msg.attachment_names
                    return ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
                return ""
        return ""


class MessageTableView(QTableView):
    """
    Configured QTableView with context menu actions for bulk operations.
    Emits action signals that MainWindow connects to workers.
    """
    detach_requested = pyqtSignal(list)    # list[Message]
    backup_requested = pyqtSignal(list)    # list[Message]
    delete_requested = pyqtSignal(list)    # list[Message]
    view_headers_requested = pyqtSignal(object)  # Message

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = MessageTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self._proxy)

        self._configure_view()
        self._build_context_menu()

    def _configure_view(self) -> None:
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)

        hh = self.horizontalHeader()
        hh.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(COL_CHECK, 28)
        hh.setSectionResizeMode(COL_FROM, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(COL_FROM, 200)
        hh.setSectionResizeMode(COL_SUBJECT, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_DATE, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(COL_DATE, 90)
        hh.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(COL_SIZE, 80)
        hh.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(COL_FOLDER, 130)
        hh.setSectionResizeMode(COL_ATTACHMENTS, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(COL_ATTACHMENTS, 160)

    def _build_context_menu(self) -> None:
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos) -> None:
        selected = self._selected_messages()
        if not selected:
            return

        menu = QMenu(self)
        detach_act = menu.addAction(f"Detach Attachments ({len(selected)} msg(s))")
        backup_act = menu.addAction(f"Backup & Delete ({len(selected)} msg(s))")
        delete_act = menu.addAction(f"Delete ({len(selected)} msg(s))")
        menu.addSeparator()
        headers_act = menu.addAction("View Headers…")

        detach_act.triggered.connect(lambda: self.detach_requested.emit(selected))
        backup_act.triggered.connect(lambda: self.backup_requested.emit(selected))
        delete_act.triggered.connect(lambda: self.delete_requested.emit(selected))
        headers_act.triggered.connect(
            lambda: self.view_headers_requested.emit(selected[0]) if selected else None
        )

        menu.exec(self.viewport().mapToGlobal(pos))

    def _selected_messages(self) -> list[Message]:
        indices = self.selectionModel().selectedRows()
        return self._model.get_selected_messages(indices)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def source_model(self) -> MessageTableModel:
        return self._model

    def set_messages(self, messages: list[Message]) -> None:
        self._model.set_messages(messages)

    def append_messages(self, messages: list[Message]) -> None:
        self._model.append_messages(messages)

    def get_checked_messages(self) -> list[Message]:
        return self._model.get_checked_messages()

    def get_selected_messages(self) -> list[Message]:
        return self._selected_messages()

    def clear(self) -> None:
        self._model.clear()
