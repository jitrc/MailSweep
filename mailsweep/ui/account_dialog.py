"""Account dialog — add or edit an IMAP account."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mailsweep.models.account import Account, AuthType
from mailsweep.utils.keyring_store import set_password


class AccountDialog(QDialog):
    """Dialog for adding or editing an IMAP account."""

    def __init__(
        self, parent: QWidget | None = None, account: Account | None = None
    ) -> None:
        super().__init__(parent)
        self._account = account
        self.setWindowTitle("Edit Account" if account else "Add Account")
        self.setMinimumWidth(420)
        self._build_ui()
        if account:
            self._populate(account)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._display_name = QLineEdit()
        self._display_name.setPlaceholderText("Work Gmail")
        form.addRow("Display Name:", self._display_name)

        self._host = QLineEdit()
        self._host.setPlaceholderText("imap.gmail.com")
        form.addRow("IMAP Host:", self._host)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(993)
        form.addRow("Port:", self._port)

        self._username = QLineEdit()
        self._username.setPlaceholderText("user@example.com")
        form.addRow("Username:", self._username)

        self._auth_type = QComboBox()
        self._auth_type.addItem("Password", AuthType.PASSWORD)
        self._auth_type.addItem("Gmail OAuth2", AuthType.OAUTH2_GMAIL)
        self._auth_type.addItem("Outlook OAuth2", AuthType.OAUTH2_OUTLOOK)
        self._auth_type.currentIndexChanged.connect(self._on_auth_type_changed)
        form.addRow("Auth Type:", self._auth_type)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("stored in system keyring")
        self._password_label = QLabel("Password:")
        form.addRow(self._password_label, self._password)

        self._authorize_btn = QPushButton("Authorize in Browser…")
        self._authorize_btn.clicked.connect(self._on_authorize)
        self._authorize_label = QLabel("OAuth2:")
        self._authorize_label.setVisible(False)
        self._authorize_btn.setVisible(False)
        form.addRow(self._authorize_label, self._authorize_btn)

        self._use_ssl = QCheckBox("Use SSL/TLS")
        self._use_ssl.setChecked(True)
        form.addRow("", self._use_ssl)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, account: Account) -> None:
        self._display_name.setText(account.display_name)
        self._host.setText(account.host)
        self._port.setValue(account.port)
        self._username.setText(account.username)
        idx = self._auth_type.findData(account.auth_type)
        if idx >= 0:
            self._auth_type.setCurrentIndex(idx)
        self._use_ssl.setChecked(account.use_ssl)

    def _on_auth_type_changed(self) -> None:
        auth_type = self._auth_type.currentData()
        is_password = auth_type == AuthType.PASSWORD
        self._password_label.setVisible(is_password)
        self._password.setVisible(is_password)
        self._authorize_label.setVisible(not is_password)
        self._authorize_btn.setVisible(not is_password)

    def _on_authorize(self) -> None:
        auth_type = self._auth_type.currentData()
        username = self._username.text().strip()
        if not username:
            QMessageBox.warning(self, "Missing Username", "Enter a username first.")
            return

        if auth_type == AuthType.OAUTH2_GMAIL:
            client_id, ok = _ask_text(self, "Gmail Client ID", "Enter your OAuth2 Client ID:")
            if not ok or not client_id:
                return
            client_secret, ok = _ask_text(self, "Gmail Client Secret", "Enter your OAuth2 Client Secret:")
            if not ok or not client_secret:
                return
            from mailsweep.imap.oauth2 import authorize_gmail
            token = authorize_gmail(username, client_id, client_secret)
            if token:
                QMessageBox.information(self, "Authorized", f"Gmail account {username} authorized successfully.")
            else:
                QMessageBox.critical(self, "Auth Failed", "Gmail authorization failed. Check the console for details.")

        elif auth_type == AuthType.OAUTH2_OUTLOOK:
            client_id, ok = _ask_text(self, "Outlook Client ID", "Enter your Azure App Client ID:")
            if not ok or not client_id:
                return
            from mailsweep.imap.oauth2 import authorize_outlook
            token = authorize_outlook(username, client_id)
            if token:
                QMessageBox.information(self, "Authorized", f"Outlook account {username} authorized successfully.")
            else:
                QMessageBox.critical(self, "Auth Failed", "Outlook authorization failed. Check the console for details.")

    def _on_accept(self) -> None:
        host = self._host.text().strip()
        username = self._username.text().strip()
        if not host or not username:
            QMessageBox.warning(self, "Missing Fields", "Host and Username are required.")
            return

        auth_type = self._auth_type.currentData()
        if auth_type == AuthType.PASSWORD:
            password = self._password.text()
            if password:
                set_password(username, host, password)

        self.accept()

    def get_account(self) -> Account:
        """Return the Account configured by this dialog."""
        return Account(
            id=self._account.id if self._account else None,
            display_name=self._display_name.text().strip() or self._username.text().strip(),
            host=self._host.text().strip(),
            port=self._port.value(),
            username=self._username.text().strip(),
            auth_type=self._auth_type.currentData(),
            use_ssl=self._use_ssl.isChecked(),
        )


def _ask_text(parent: QWidget, title: str, label: str) -> tuple[str, bool]:
    from PyQt6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(parent, title, label)
    return text.strip(), ok
