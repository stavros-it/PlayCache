#!/usr/bin/env python3
"""Entry point: launch the PlayCache GUI (console variant for debugging)."""
import argparse
import logging
import sys

from PySide6.QtWidgets import QApplication

from playcache import __version__
from playcache.config import Config
from playcache.gui import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(prog="playcache", description="PlayCache GUI")
    parser.add_argument(
        "--version", action="version", version=f"PlayCache {__version__}"
    )
    parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("PlayCache")
    app.setApplicationVersion(__version__)
    config = Config.load()
    window = MainWindow(config)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
