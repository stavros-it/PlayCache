#!/usr/bin/env python3
"""Entry point: launch the PlayCache GUI (console variant for debugging)."""
import logging
import sys

from PySide6.QtWidgets import QApplication

from playcache.config import Config
from playcache.gui import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("PlayCache")
    config = Config.load()
    window = MainWindow(config)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
