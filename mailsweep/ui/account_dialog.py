"""Account dialog — add or edit an IMAP account."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mailsweep.models.account import Account, AuthType
from mailsweep.utils.keyring_store import set_password

logger = logging.getLogger(__name__)

_GMAIL_HELP = """\
<b>Gmail OAuth2 requires your own Google Cloud credentials.</b><br><br>
<b>Simpler alternative:</b> Use <b>Auth Type: Password</b> with a
<a href="https://myaccount.google.com/apppasswords">Gmail App Password</a>
(requires 2-Step Verification enabled). This works without any setup.<br><br>
<b>To use OAuth2:</b><br>
1. Go to <a href="https://console.cloud.google.com/">Google Cloud Console</a><br>
2. Create a project → APIs &amp; Services → Credentials<br>
3. Create an <i>OAuth 2.0 Client ID</i> (Desktop app type)<br>
4. Copy the Client ID and Client Secret below."""

_OUTLOOK_HELP = """\
<b>Outlook OAuth2 requires an Azure App Registration.</b><br><br>
1. Go to <a href="https://portal.azure.com/">Azure Portal</a> →
   Azure Active Directory → App registrations<br>
2. New registration → choose <i>Accounts in any organizational directory
   and personal Microsoft accounts</i><br>
3. Add a Mobile/Desktop redirect URI: <code>https://login.microsoftonline.com/common/oauth2/nativeclient</code><br>
4. Copy the Application (client) ID below."""


class _OAuthWorker(QObject):
    """Runs the blocking OAuth browser flow on a background thread."""
    success = pyqtSignal(str)   # access_token
    failure = pyqtSignal(str)   # error message
    finished = pyqtSignal()

    def __init__(self, auth_type: AuthType, username: str,
                 client_id: str, client_secret: str = "") -> None:
        super().__init__()
        self._auth_type = auth_type
        self._username = username
        self._client_id = client_id
        self._client_secret = client_secret

    def run(self) -> None:
        try:
            if self._auth_type == AuthType.OAUTH2_GMAIL:
                from mailsweep.imap.oauth2 import authorize_gmail
                token = authorize_gmail(self._username, self._client_id, self._client_secret)
            else:
                from mailsweep.imap.oauth2 import authorize_outlook
                token = authorize_outlook(self._username, self._client_id)

            if token:
                self.success.emit(token)
            else:
                self.failure.emit("Authorization returned no token. Check the browser and try again.")
        except Exception as exc:
            logger.exception("OAuth worker error")
            self.failure.emit(str(exc))
        finally:
            self.finished.emit()


class AccountDialog(QDialog):
    """Dialog for adding or editing an IMAP account."""

    def __init__(
        self, parent: QWidget | None = None, account: Account | None = None
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._oauth_thread: QThread | None = None
        self._oauth_progress: QProgressDialog | None = None
        self.setWindowTitle("Edit Account" if account else "Add Account")
        self.setMinimumWidth(460)
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
        self._auth_type.addItem("Password / App Password", AuthType.PASSWORD)
        self._auth_type.addItem("Gmail OAuth2", AuthType.OAUTH2_GMAIL)
        self._auth_type.addItem("Outlook OAuth2", AuthType.OAUTH2_OUTLOOK)
        self._auth_type.currentIndexChanged.connect(self._on_auth_type_changed)
        form.addRow("Auth Type:", self._auth_type)

        # Password row
        self._password_label = QLabel("Password:")
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("password or App Password")
        form.addRow(self._password_label, self._password)

        # Help label (hidden by default, shown for OAuth2)
        self._help_label = QLabel()
        self._help_label.setWordWrap(True)
        self._help_label.setOpenExternalLinks(True)
        self._help_label.setVisible(False)
        self._help_label.setMaximumWidth(420)
        form.addRow("", self._help_label)

        # OAuth2 credential fields (hidden by default)
        self._client_id_label = QLabel("Client ID:")
        self._client_id_edit = QLineEdit()
        self._client_id_edit.setPlaceholderText("paste from Google/Azure console")
        self._client_id_label.setVisible(False)
        self._client_id_edit.setVisible(False)
        form.addRow(self._client_id_label, self._client_id_edit)

        self._client_secret_label = QLabel("Client Secret:")
        self._client_secret_edit = QLineEdit()
        self._client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._client_secret_edit.setPlaceholderText("Gmail only — leave blank for Outlook")
        self._client_secret_label.setVisible(False)
        self._client_secret_edit.setVisible(False)
        form.addRow(self._client_secret_label, self._client_secret_edit)

        # Authorize button row
        self._authorize_label = QLabel("OAuth2:")
        auth_row = QHBoxLayout()
        self._authorize_btn = QPushButton("Authorize in Browser…")
        self._authorize_btn.clicked.connect(self._on_authorize)
        self._authorize_status = QLabel()
        auth_row.addWidget(self._authorize_btn)
        auth_row.addWidget(self._authorize_status)
        self._authorize_label.setVisible(False)
        self._authorize_btn.setVisible(False)
        self._authorize_status.setVisible(False)
        form.addRow(self._authorize_label, auth_row)

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
        is_gmail = auth_type == AuthType.OAUTH2_GMAIL
        is_outlook = auth_type == AuthType.OAUTH2_OUTLOOK
        is_oauth = is_gmail or is_outlook

        self._password_label.setVisible(is_password)
        self._password.setVisible(is_password)

        self._help_label.setVisible(is_oauth)
        self._help_label.setText(_GMAIL_HELP if is_gmail else _OUTLOOK_HELP)

        self._client_id_label.setVisible(is_oauth)
        self._client_id_edit.setVisible(is_oauth)
        self._client_secret_label.setVisible(is_gmail)
        self._client_secret_edit.setVisible(is_gmail)

        self._authorize_label.setVisible(is_oauth)
        self._authorize_btn.setVisible(is_oauth)
        self._authorize_status.setVisible(is_oauth)

        # Auto-fill host for known providers
        if is_gmail and not self._host.text():
            self._host.setText("imap.gmail.com")
            self._port.setValue(993)
        elif is_outlook and not self._host.text():
            self._host.setText("outlook.office365.com")
            self._port.setValue(993)

        self.adjustSize()

    def _on_authorize(self) -> None:
        if self._oauth_thread and self._oauth_thread.isRunning():
            return

        auth_type = self._auth_type.currentData()
        username = self._username.text().strip()
        if not username:
            QMessageBox.warning(self, "Missing Username", "Enter your email address first.")
            return

        client_id = self._client_id_edit.text().strip()
        if not client_id:
            QMessageBox.warning(self, "Missing Client ID",
                                "Paste your Client ID from the Google/Azure console first.")
            return

        client_secret = self._client_secret_edit.text().strip()
        if auth_type == AuthType.OAUTH2_GMAIL and not client_secret:
            QMessageBox.warning(self, "Missing Client Secret",
                                "Gmail OAuth2 requires a Client Secret.")
            return

        # Run the blocking browser flow in a background thread
        worker = _OAuthWorker(auth_type, username, client_id, client_secret)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.success.connect(self._on_oauth_success)
        worker.failure.connect(self._on_oauth_failure)

        self._oauth_thread = thread
        self._authorize_btn.setEnabled(False)
        self._authorize_status.setText("Opening browser…")
        self._authorize_status.setVisible(True)

        thread.start()

    def _on_oauth_success(self, token: str) -> None:
        self._authorize_btn.setEnabled(True)
        self._authorize_status.setText("Authorized!")
        self._authorize_status.setStyleSheet("color: green; font-weight: bold;")
        self._oauth_thread = None

    def _on_oauth_failure(self, error: str) -> None:
        self._authorize_btn.setEnabled(True)
        self._authorize_status.setText("Failed")
        self._authorize_status.setStyleSheet("color: red;")
        self._oauth_thread = None
        QMessageBox.critical(self, "Authorization Failed",
                             f"OAuth2 authorization failed:\n\n{error}")

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
        elif auth_type in (AuthType.OAUTH2_GMAIL, AuthType.OAUTH2_OUTLOOK):
            # Verify a token was actually obtained
            from mailsweep.utils.keyring_store import get_token
            prefix = "gmail" if auth_type == AuthType.OAUTH2_GMAIL else "outlook"
            if not get_token(f"{prefix}:{username}"):
                reply = QMessageBox.question(
                    self, "Not Authorized",
                    "No OAuth2 token found for this account.\n"
                    "Save anyway? (You can authorize later.)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        self.accept()

    def get_account(self) -> Account:
        return Account(
            id=self._account.id if self._account else None,
            display_name=self._display_name.text().strip() or self._username.text().strip(),
            host=self._host.text().strip(),
            port=self._port.value(),
            username=self._username.text().strip(),
            auth_type=self._auth_type.currentData(),
            use_ssl=self._use_ssl.isChecked(),
        )
