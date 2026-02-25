"""Folder panel — QTreeWidget showing folder hierarchy with size badges."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from mailsweep.models.folder import Folder
from mailsweep.utils.size_fmt import human_size

FOLDER_ID_ROLE = Qt.ItemDataRole.UserRole
ALL_FOLDERS_ID = -1  # Sentinel meaning "show all"


class FolderPanel(QTreeWidget):
    """
    Shows folder tree with size badges.
    Emits folder_selected(folder_ids) when user clicks a folder.
    folder_ids is empty list to mean "all folders".
    """
    folder_selected = pyqtSignal(list)  # list[int] of folder_ids

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Folder", "Size"])
        self.setColumnWidth(0, 180)
        self.setColumnWidth(1, 80)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.itemClicked.connect(self._on_item_clicked)
        self._add_all_item()

    def _add_all_item(self) -> None:
        all_item = QTreeWidgetItem(["All Folders", ""])
        all_item.setData(0, FOLDER_ID_ROLE, ALL_FOLDERS_ID)
        font = QFont()
        font.setBold(True)
        all_item.setFont(0, font)
        self.addTopLevelItem(all_item)

    def populate(self, folders: list[Folder]) -> None:
        """Rebuild the tree from a flat list of folders."""
        # Keep the "All Folders" sentinel
        self.clear()
        self._add_all_item()

        total_size = sum(f.total_size_bytes for f in folders)
        all_item = self.topLevelItem(0)
        if all_item:
            all_item.setText(1, human_size(total_size))

        # Build nested tree from folder paths
        # Folders may be separated by "/" or "."
        items_by_path: dict[str, QTreeWidgetItem] = {}

        for folder in sorted(folders, key=lambda f: f.name):
            parts = folder.name.replace(".", "/").split("/")
            parent_item: QTreeWidgetItem | QTreeWidget = self

            for depth, part in enumerate(parts):
                path_key = "/".join(parts[: depth + 1])
                if path_key in items_by_path:
                    parent_item = items_by_path[path_key]
                    continue

                is_leaf = depth == len(parts) - 1
                item = QTreeWidgetItem([part, human_size(folder.total_size_bytes) if is_leaf else ""])
                item.setData(0, FOLDER_ID_ROLE, folder.id if is_leaf else None)

                if isinstance(parent_item, QTreeWidget):
                    parent_item.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)

                items_by_path[path_key] = item
                parent_item = item

        self.expandAll()

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        fid = item.data(0, FOLDER_ID_ROLE)
        if fid == ALL_FOLDERS_ID:
            self.folder_selected.emit([])
        elif fid is not None:
            self.folder_selected.emit([fid])
        # Intermediate nodes (None) do nothing

    def update_folder_size(self, folder_id: int, size_bytes: int) -> None:
        """Update the size badge for a single folder."""
        root = self.invisibleRootItem()
        self._update_item_size(root, folder_id, size_bytes)

    def _update_item_size(
        self, parent: QTreeWidgetItem, folder_id: int, size_bytes: int
    ) -> bool:
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child is None:
                continue
            if child.data(0, FOLDER_ID_ROLE) == folder_id:
                child.setText(1, human_size(size_bytes))
                return True
            if self._update_item_size(child, folder_id, size_bytes):
                return True
        return False
