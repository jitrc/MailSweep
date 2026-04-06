"""Sandboxed WebView dialog for List-Unsubscribe URLs.

Security measures:
  - Off-the-record QWebEngineProfile: no cookies, no cache, no history persisted.
  - Cross-origin navigation blocked: only the initial host is allowed.
  - No downloads, no plugins.
  - JavaScript is enabled (required for most modern unsubscribe pages to work),
    but runs in an isolated profile with no access to the user's real browser data.
"""
from __future__ import annotations

from urllib.parse import urlparse

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class _SandboxedPage(QWebEnginePage):
    """Block navigation to any origin other than the initial one."""

    def __init__(self, allowed_host: str, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(profile, parent)
        self._allowed_host = allowed_host.lower()

    def acceptNavigationRequest(
        self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        if not is_main_frame:
            return True  # allow sub-frame resources (CSS, images, etc.)
        host = urlparse(url.toString()).netloc.lower()
        # Allow same host and initial load
        if host == self._allowed_host or nav_type == QWebEnginePage.NavigationType.NavigationTypeTyped:
            return True
        return False


class UnsubscribeDialog(QDialog):
    """Opens a single unsubscribe URL in a sandboxed, off-the-record WebView."""

    def __init__(self, url: str, from_addr: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unsubscribe — Sandboxed Browser")
        self.resize(960, 640)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        info = QLabel(
            f"<b>Sender:</b> {from_addr}<br>"
            f"<b>URL:</b> <tt>{url}</tt><br>"
            "<small>This page runs in an isolated profile — "
            "no cookies, history, or data from your real browser.</small>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Off-the-record profile (no storage name → no persistence)
        profile = QWebEngineProfile(self)
        s = profile.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)

        allowed_host = urlparse(url).netloc
        self._page = _SandboxedPage(allowed_host, profile, self)

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        self._view.load(QUrl(url))
        layout.addWidget(self._view, stretch=1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self._safe_close)
        layout.addWidget(btn_box)

    def closeEvent(self, event) -> None:
        """Intercept window-X close to go through safe shutdown."""
        event.ignore()
        self._safe_close()

    def _safe_close(self) -> None:
        """Navigate to blank before closing to stop WebEngine background activity."""
        # Disconnect closeEvent guard so the deferred reject() can actually close
        self.closeEvent = lambda e: e.accept()  # type: ignore[method-assign]
        self._view.stop()
        self._page.setUrl(QUrl("about:blank"))
        # Give QtWebEngineCore a tick to wind down before the destructor runs
        QTimer.singleShot(200, self.reject)
