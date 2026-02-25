"""PyInstaller runtime hook: set SSL_CERT_FILE from bundled certifi."""
import os
import sys


def _setup_certs():
    if getattr(sys, 'frozen', False):
        try:
            import certifi
            os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        except ImportError:
            pass


_setup_certs()
