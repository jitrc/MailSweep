"""Filter bar — sender, subject, date range, size range, has-attachment filter."""
from __future__ import annotations

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class FilterBar(QWidget):
    """
    Horizontal filter bar.  Emits filter_changed when Apply is clicked.
    """
    filter_changed = pyqtSignal(dict)  # filter kwargs for MessageRepository.query_messages

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        layout.addWidget(QLabel("From:"))
        self._from_edit = QLineEdit()
        self._from_edit.setPlaceholderText("sender")
        self._from_edit.setFixedWidth(140)
        layout.addWidget(self._from_edit)

        layout.addWidget(QLabel("Subject:"))
        self._subject_edit = QLineEdit()
        self._subject_edit.setPlaceholderText("keyword")
        self._subject_edit.setFixedWidth(140)
        layout.addWidget(self._subject_edit)

        layout.addWidget(QLabel("From:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate(2000, 1, 1))
        self._date_from.setFixedWidth(110)
        layout.addWidget(self._date_from)

        layout.addWidget(QLabel("To:"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setFixedWidth(110)
        layout.addWidget(self._date_to)

        layout.addWidget(QLabel("Size MB ≥"))
        self._size_min = QDoubleSpinBox()
        self._size_min.setRange(0, 10000)
        self._size_min.setDecimals(1)
        self._size_min.setFixedWidth(70)
        layout.addWidget(self._size_min)

        layout.addWidget(QLabel("≤"))
        self._size_max = QDoubleSpinBox()
        self._size_max.setRange(0, 10000)
        self._size_max.setDecimals(1)
        self._size_max.setFixedWidth(70)
        layout.addWidget(self._size_max)

        self._has_attachment = QCheckBox("Has Attachments")
        layout.addWidget(self._has_attachment)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(60)
        apply_btn.clicked.connect(self._emit_filter)
        layout.addWidget(apply_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(50)
        clear_btn.clicked.connect(self._clear_and_emit)
        layout.addWidget(clear_btn)

        layout.addStretch()

        # Apply on Enter in text fields
        self._from_edit.returnPressed.connect(self._emit_filter)
        self._subject_edit.returnPressed.connect(self._emit_filter)

    def _emit_filter(self) -> None:
        kwargs: dict = {}

        from_text = self._from_edit.text().strip()
        if from_text:
            kwargs["from_filter"] = from_text

        subject_text = self._subject_edit.text().strip()
        if subject_text:
            kwargs["subject_filter"] = subject_text

        date_from = self._date_from.date()
        if date_from > QDate(2000, 1, 1):
            kwargs["date_from"] = date_from.toString("yyyy-MM-dd")

        date_to = self._date_to.date()
        if date_to < QDate.currentDate():
            kwargs["date_to"] = date_to.toString("yyyy-MM-dd")

        size_min = self._size_min.value()
        if size_min > 0:
            kwargs["size_min"] = int(size_min * 1024 * 1024)

        size_max = self._size_max.value()
        if size_max > 0:
            kwargs["size_max"] = int(size_max * 1024 * 1024)

        if self._has_attachment.isChecked():
            kwargs["has_attachment"] = True

        self.filter_changed.emit(kwargs)

    def _clear_and_emit(self) -> None:
        self._from_edit.clear()
        self._subject_edit.clear()
        self._date_from.setDate(QDate(2000, 1, 1))
        self._date_to.setDate(QDate.currentDate())
        self._size_min.setValue(0)
        self._size_max.setValue(0)
        self._has_attachment.setChecked(False)
        self.filter_changed.emit({})

    def get_filter_kwargs(self) -> dict:
        """Return current filter parameters without emitting signal."""
        kwargs: dict = {}
        from_text = self._from_edit.text().strip()
        if from_text:
            kwargs["from_filter"] = from_text
        subject_text = self._subject_edit.text().strip()
        if subject_text:
            kwargs["subject_filter"] = subject_text
        size_min = self._size_min.value()
        if size_min > 0:
            kwargs["size_min"] = int(size_min * 1024 * 1024)
        size_max = self._size_max.value()
        if size_max > 0:
            kwargs["size_max"] = int(size_max * 1024 * 1024)
        if self._has_attachment.isChecked():
            kwargs["has_attachment"] = True
        return kwargs
