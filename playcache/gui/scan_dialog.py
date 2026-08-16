"""Scan configuration dialog and background scan worker thread."""
from __future__ import annotations

import logging

from PySide6.QtCore import QEventLoop, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..cataloger import Cataloger
from ..config import Config

log = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Runs Cataloger.scan_to_db off the GUI thread."""

    progress = Signal(int, int, str)        # idx, total, message
    finished = Signal(dict)                  # summary
    failed = Signal(str)                     # error message
    conflict = Signal(object, object)        # new_record, existing_record

    def __init__(
        self,
        cataloger: Cataloger,
        root: str,
        *,
        rescan: bool = False,
        only_missing: bool = True,
        limit: int | None = None,
        name_filter: str = "",
        dry_run: bool = False,
        recursive: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._cataloger = cataloger
        self._root = root
        self._rescan = rescan
        self._only_missing = only_missing
        self._limit = limit
        self._name_filter = name_filter or None
        self._dry_run = dry_run
        self._recursive = recursive
        self._cancelled = False
        self._conflict_response: str = ""

    def cancel(self) -> None:
        self._cancelled = True

    def set_conflict_response(self, choice: str) -> None:
        """Called from the GUI thread to unblock a conflict prompt."""
        self._conflict_response = choice

    def run(self) -> None:
        try:
            def on_progress(idx: int, total: int, _record, message: str) -> None:
                if self._cancelled:
                    raise InterruptedError("scan cancelled")
                self.progress.emit(idx, total, message)

            def on_conflict(new_rec, existing_rec) -> str:
                # Block the worker thread until the GUI responds.
                self._conflict_response = ""
                self.conflict.emit(new_rec, existing_rec)
                loop = QEventLoop()
                # Poll-wait: the GUI thread will call set_conflict_response,
                # which we detect here. Using a loop with processEvents
                # avoids a hard deadlock.
                while not self._conflict_response and not self._cancelled:
                    loop.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 100)
                return self._conflict_response or "both"

            summary = self._cataloger.scan_to_db(
                self._root,
                rescan=self._rescan,
                only_missing=self._only_missing,
                limit=self._limit,
                name_filter=self._name_filter,
                dry_run=self._dry_run,
                recursive=self._recursive,
                progress=on_progress,
                conflict_handler=on_conflict,
            )
            self.finished.emit(summary)
        except InterruptedError:
            self.finished.emit({"cancelled": True})
        except Exception as e:
            log.exception("Scan failed")
            self.failed.emit(str(e))


class ScanDialog(QDialog):
    """Modal-ish dialog for configuring and running a scan with live progress."""

    def __init__(self, cataloger: Cataloger, config: Config,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Scan Game Folders")
        self.setMinimumWidth(560)
        self._cataloger = cataloger
        self._config = config
        self._worker: ScanWorker | None = None

        layout = QVBoxLayout(self)

        # --- Folder picker ---
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Drive or folder:"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("e.g. D: or D:\\Games")
        folder_row.addWidget(self.path_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        # --- Options ---
        form = QFormLayout()
        self.rescan_check = QCheckBox("Re-fetch metadata for all games (ignore cached)")
        self.only_missing_check = QCheckBox("Only fetch games not yet catalogued")
        self.only_missing_check.setChecked(True)
        self.recursive_check = QCheckBox("Descend into grouping folders")
        self.dry_run_check = QCheckBox("Dry-run (scan only, no API calls or DB writes)")

        options_row1 = QHBoxLayout()
        options_row1.addWidget(self.rescan_check)
        options_row1.addWidget(self.only_missing_check)
        layout.addLayout(options_row1)
        options_row2 = QHBoxLayout()
        options_row2.addWidget(self.recursive_check)
        options_row2.addWidget(self.dry_run_check)
        layout.addLayout(options_row2)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Only folders containing this substring")
        form.addRow("Filter:", self.filter_edit)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 100000)
        self.limit_spin.setSpecialValueText("No limit")
        form.addRow("Max folders:", self.limit_spin)
        layout.addLayout(form)

        # --- Progress ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_label = QLabel("Ready.")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Scan log will appear here…")
        layout.addWidget(self.log_view, 1)

        # --- Buttons ---
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, parent=self
        )
        self.start_btn = self.buttons.addButton(
            "Start Scan", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.start_btn.clicked.connect(self._start)
        self.buttons.rejected.connect(self._on_close)
        layout.addWidget(self.buttons)

    # ------------------------------------------------------------------ #
    def _browse(self) -> None:
        # Use a directory dialog; allow drive letters too
        path = QFileDialog.getExistingDirectory(
            self, "Select drive or folder", self.path_edit.text() or ""
        )
        if path:
            self.path_edit.setText(path)

    # ------------------------------------------------------------------ #
    def _start(self) -> None:
        root = self.path_edit.text().strip()
        if not root:
            QMessageBox.warning(self, "No path", "Please enter a drive or folder to scan.")
            return

        self.start_btn.setEnabled(False)
        self.log_view.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting…")

        self._worker = ScanWorker(
            self._cataloger,
            root,
            rescan=self.rescan_check.isChecked(),
            only_missing=self.only_missing_check.isChecked(),
            limit=self.limit_spin.value() or None,
            name_filter=self.filter_edit.text().strip(),
            dry_run=self.dry_run_check.isChecked(),
            recursive=self.recursive_check.isChecked(),
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.conflict.connect(self._on_conflict)
        self._worker.start()

    def _on_progress(self, idx: int, total: int, message: str) -> None:
        pct = int(idx * 100 / total) if total else 0
        self.progress_bar.setValue(pct)
        self.progress_label.setText(f"[{idx}/{total}] {message}")
        self.log_view.append(f"[{idx}/{total}] {message}")

    def _on_conflict(self, new_rec, existing_rec) -> None:
        """Prompt the user to resolve a disk conflict (same game, different disk)."""
        name = new_rec.game_name or new_rec.folder_name
        msg = (
            f"'{name}' already exists in the catalog on a different disk:\n\n"
            f"  Existing: {existing_rec.disk}  ({existing_rec.store or '?'})\n"
            f"  {existing_rec.folder_path}\n\n"
            f"  New scan: {new_rec.disk}  ({new_rec.store or '?'})\n"
            f"  {new_rec.folder_path}\n\n"
            f"Which copy do you want to keep?"
        )
        box = QMessageBox(self)
        box.setWindowTitle("Duplicate found on another disk")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(msg)
        keep_new = box.addButton("Keep new", QMessageBox.ButtonRole.AcceptRole)
        keep_old = box.addButton("Keep existing", QMessageBox.ButtonRole.RejectRole)
        box.addButton("Keep both", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is keep_new:
            self._worker.set_conflict_response("new")
            self.log_view.append(f"  → kept new copy on {new_rec.disk}")
        elif box.clickedButton() is keep_old:
            self._worker.set_conflict_response("old")
            self.log_view.append(f"  → kept existing copy on {existing_rec.disk}")
        else:
            self._worker.set_conflict_response("both")
            self.log_view.append("  → kept both copies")

    def _on_finished(self, summary: dict) -> None:
        self.start_btn.setEnabled(True)
        if summary.get("cancelled"):
            self.progress_label.setText("Scan cancelled.")
            self.log_view.append("\n— Scan cancelled —")
            return
        self.progress_bar.setValue(100)
        lines = [
            "",
            "— Scan complete —",
            f"Folders scanned : {summary.get('scanned', 0)}",
            f"Processed       : {summary.get('processed', 0)}",
            f"Fetched OK     : {summary.get('ok', 0)}",
            f"Not found       : {summary.get('not_found', 0)}",
            f"Errors          : {summary.get('error', 0)}",
            f"Skipped         : {summary.get('skipped', 0)}",
            f"Disk conflicts  : {summary.get('conflicts', 0)}",
            f"Stored in DB    : {summary.get('stored', 0)}",
        ]
        self.log_view.append("\n".join(lines))
        self.progress_label.setText(
            f"Done: {summary.get('ok', 0)} ok, "
            f"{summary.get('not_found', 0)} not found, "
            f"{summary.get('error', 0)} errors."
        )

    def _on_failed(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        self.progress_label.setText("Scan failed.")
        self.log_view.append(f"\nERROR: {message}")
        QMessageBox.critical(self, "Scan failed", message)

    def _on_close(self) -> None:
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "Cancel scan?",
                "A scan is in progress. Cancel and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._worker.cancel()
            # Give the worker time to wind down. If it's still inside a long
            # network call, don't destroy the QThread — that crashes Qt. Detach
            # the worker so it can finish on its own, then close the dialog.
            if not self._worker.wait(3000):
                log.warning("Scan worker did not stop within 3s; detaching.")
                self._worker.finished.connect(self._worker.deleteLater)
                self._worker = None
            else:
                self._worker.deleteLater()
                self._worker = None
        self.reject()
