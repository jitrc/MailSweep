"""MailSweep — entry point for the GUI application."""
from __future__ import annotations

import logging
import sys

from mailsweep.config import LOG_PATH


def _setup_logging() -> None:
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )


def main() -> None:
    _setup_logging()
    try:
        from pathlib import Path

        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QApplication
        from mailsweep.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName("MailSweep")
        app.setOrganizationName("MailSweep")

        icon_path = Path(__file__).resolve().parent / "resources" / "icon.svg"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))

        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except ImportError as exc:
        logging.error("PyQt6 not available: %s — running CLI fallback", exc)
        from mailsweep.cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
