#!/usr/bin/env python3
"""GUI launcher (no console window on Windows).

Run by double-clicking this file, or with `pythonw run.pyw`. Because
``pythonw.exe`` disconnects stdout/stderr, diagnostics are redirected to
``playcache.log`` in the working directory; fatal startup errors are also
shown in a message box. Set ``PLAYCACHE_DEBUG=1`` for verbose logging.
"""
import logging
import os
import sys
from pathlib import Path


def _redirect_streams() -> Path:
    """Redirect stdout/stderr to a log file when running under pythonw.exe.

    Under ``pythonw.exe`` both streams are ``None``; writing to them raises
    "Bad file descriptor". We point them at a log file so tracebacks survive.
    When launched from a terminal (``python.exe``), the real streams are kept.
    """
    log_path = Path("playcache.log")
    try:
        stream = log_path.open("a", encoding="utf-8")
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - keep open
        log_path = Path(os.devnull)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return log_path


def _setup_logging() -> None:
    level = logging.DEBUG if os.getenv("PLAYCACHE_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


def _show_fatal_error(exc: BaseException, log_path: Path) -> None:
    """Show a message box for a fatal startup error, if Qt is importable."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "PlayCache failed to start",
            f"{type(exc).__name__}: {exc}\n\n"
            f"Diagnostics written to:\n{log_path.resolve()}",
        )
    except Exception:  # noqa: BLE001 - nothing more we can do without Qt
        # If Qt itself is unavailable, fall back to stderr (if it exists) so
        # the user has at least some diagnostic output.
        if sys.stderr:
            sys.stderr.write(
                f"PlayCache fatal error: {exc}\n"
                f"Diagnostics: {log_path.resolve()}\n"
            )


def main() -> int:
    log_path = _redirect_streams()
    _setup_logging()
    log = logging.getLogger("launcher")

    try:
        import argparse

        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from playcache import __version__
        from playcache.config import Config
        from playcache.gui import MainWindow

        parser = argparse.ArgumentParser(prog="playcache", description="PlayCache GUI")
        parser.add_argument(
            "--version", action="version", version=f"PlayCache {__version__}"
        )
        parser.parse_args()

        app = QApplication(sys.argv)
        app.setApplicationName("PlayCache")
        app.setApplicationVersion(__version__)

        # Set the app icon early (taskbar + Alt-Tab on Windows)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "PlayCache.App"
                )
            except (OSError, AttributeError):
                pass
        icon_path = Path(__file__).resolve().parent / "playcache" / "assets" / "app.ico"
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))

        config = Config.load()
        window = MainWindow(config)
        window.showMaximized()
        return app.exec()
    except Exception as exc:  # surface any startup failure to the user
        log.exception("Fatal error during startup")
        _show_fatal_error(exc, log_path)
        return 1


if __name__ == "__main__":
    sys.exit(main())
