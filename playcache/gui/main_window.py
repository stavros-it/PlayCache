"""Main application window: toolbar, filters, games table, detail panel."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..backup import export_backup, import_backup
from ..cataloger import Cataloger
from ..config import Config
from ..db import Database
from ..exporter import export_xlsx
from ..image_cache import ImageCache
from ..models import GameRecord
from .about_dialog import AboutDialog
from .detail_panel import DetailPanel
from .duplicates_dialog import DuplicatesDialog
from .item_delegate import GamesItemDelegate
from .scan_dialog import ScanDialog
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog
from .table_model import GamesTableModel
from .theme import DARK_QSS

log = logging.getLogger(__name__)


class GamesProxyModel(QSortFilterProxyModel):
    """Filter/sort wrapper over GamesTableModel."""

    # Column indices that need custom sort keys (must match COLUMNS in table_model)
    _GAME_COL = 0
    _RELEASED_COL = 4
    _RATING_COL = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search = ""
        self._store = "All"
        self._status = "All"

    def set_search(self, text: str) -> None:
        self._search = (text or "").lower()
        self.invalidateFilter()

    def set_store(self, store: str) -> None:
        self._store = store
        self.invalidateFilter()

    def set_status(self, status: str) -> None:
        self._status = status
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        source = self.sourceModel()
        if source is None:
            return True
        rec: GameRecord | None = source.record_at(source_row)
        if rec is None:
            return False
        if self._search and self._search not in (rec.game_name or "").lower():
            return False
        if self._store != "All" and (rec.store or "Other") != self._store:
            return False
        return self._status == "All" or (rec.fetch_status or "") == self._status

    def lessThan(self, left, right) -> bool:
        """Custom sort keys for columns where string sort gives wrong results.

        - Game (col 0): case-insensitive alphabetical (so "portal" doesn't
          sort before "Half-Life" just because lowercase > uppercase in ASCII).
        - Released (col 4): sort by ISO date (YYYY-MM-DD) so chronological order
          is correct despite the DD-MM-YYYY display format.
        - Rating (col 5): sort numerically by the score value (e.g. 9.5 out of 10)
          so "9/10" > "10/10" doesn't happen as a string comparison.
        Other columns fall back to Qt's default string comparison.
        """
        col = left.column()
        if col == self._RELEASED_COL:
            rec_l = self.sourceModel().record_at(left.row())
            rec_r = self.sourceModel().record_at(right.row())
            kl = self._date_key(rec_l.release_date)
            kr = self._date_key(rec_r.release_date)
            return kl < kr
        if col == self._RATING_COL:
            rec_l = self.sourceModel().record_at(left.row())
            rec_r = self.sourceModel().record_at(right.row())
            return self._rating_key(rec_l.user_rating) < self._rating_key(rec_r.user_rating)
        if col == self._GAME_COL:
            # Case-insensitive alphabetical, with empty strings sorting last.
            lv = (left.data(Qt.ItemDataRole.DisplayRole) or "")
            rv = (right.data(Qt.ItemDataRole.DisplayRole) or "")
            lv_low, rv_low = lv.lower(), rv.lower()
            if lv_low == rv_low:
                # Stable tiebreak: preserve original order for equal keys
                return left.row() < right.row()
            return lv_low < rv_low
        return super().lessThan(left, right)

    @staticmethod
    def _date_key(value: str | None) -> str:
        """ISO date padded to YYYY-MM-DD for chronological string sort.

        Handles partial dates: ``2023`` → ``2023-00-00``, ``2023-05`` →
        ``2023-05-00``. Empty/invalid dates sort first (oldest).
        """
        v = (value or "").strip()
        if not v:
            return "0000-00-00"
        parts = v.split("-")
        padded = []
        for i, p in enumerate(parts[:3]):
            if p.isdigit():
                padded.append(p.zfill(4) if i == 0 else p.zfill(2))
            else:
                padded.append("00" if i > 0 else "0000")
        while len(padded) < 3:
            padded.append("00")
        return "-".join(padded)

    @staticmethod
    def _rating_key(value: str | None) -> float:
        """Extract the numeric score from a rating string like '8.5/10'."""
        v = (value or "").strip()
        if not v:
            return -1.0
        num = v.split("/")[0].strip()
        try:
            return float(num)
        except ValueError:
            return -1.0


class MainWindow(QMainWindow):
    scan_requested = Signal(str, bool, bool, bool, str, int, bool)  # forwarded

    def __init__(self, config: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("PlayCache")
        self.resize(1280, 800)
        self.setStyleSheet(DARK_QSS)
        self._set_window_icon()

        self._config = config
        self._db = Database(config.db_path)
        self._cataloger = Cataloger(config, db=self._db)

        # Core data model
        self._model = GamesTableModel()
        self._model.fieldEdited.connect(self._on_field_edited)
        self._proxy = GamesProxyModel()
        self._proxy.setSourceModel(self._model)

        # Image cache
        cache_dir = str(Path(config.db_path).parent / "covers")
        self._image_cache = ImageCache(cache_dir=cache_dir, parent=self)
        self._image_cache.image_loaded.connect(self._on_image_loaded)

        self._build_ui()
        self._refresh_table()
        self._update_status_bar()
        self._fetch_quota_on_startup()

    def _fetch_quota_on_startup(self) -> None:
        """Fetch the TGDB quota in the background so the status bar shows it.

        The TGDB quota fields are only returned with API responses, so on
        startup they're unknown. We make a lightweight call to ``/Genres``
        (which we need cached anyway) to populate both the genre cache and the
        quota, then refresh the status bar. Runs on a background thread to
        avoid blocking the UI.
        """
        from PySide6.QtCore import QThread

        tgdb = self._cataloger.tgdb
        if not tgdb.is_available():
            return

        class QuotaWorker(QThread):
            done = Signal()

            def __init__(self_inner, client, parent=None):
                super().__init__(parent)
                self_inner._client = client

            def run(self_inner):
                try:
                    self_inner._client._load_genres()
                except Exception as e:  # noqa: BLE001 - best-effort quota fetch
                    log.debug("startup quota fetch failed: %s", e)
                self_inner.done.emit()

        self._quota_worker = QuotaWorker(tgdb, parent=self)
        self._quota_worker.done.connect(self._update_status_bar)
        self._quota_worker.start()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _set_window_icon(self) -> None:
        """Load the app icon from ``playcache/assets/app.ico`` and apply it.

        Bundled with the package; falls back silently if missing. On Windows
        also sets the AppUserModelID so the taskbar shows our icon instead of
        Python's.
        """
        from PySide6.QtGui import QIcon
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "PlayCache.App"
                )
            except (OSError, AttributeError):
                pass

    def _build_ui(self) -> None:
        # Toolbar
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.scan_action = QAction("Scan Drive…", self)
        self.scan_action.setShortcut(QKeySequence("Ctrl+S"))
        self.scan_action.triggered.connect(self._open_scan_dialog)
        toolbar.addAction(self.scan_action)

        self.add_game_action = QAction("Add Game…", self)
        self.add_game_action.setShortcut(QKeySequence("Ctrl+N"))
        self.add_game_action.triggered.connect(self._add_game)
        toolbar.addAction(self.add_game_action)

        self.rescan_action = QAction("Rescan All", self)
        self.rescan_action.setShortcut(QKeySequence("Ctrl+R"))
        self.rescan_action.triggered.connect(self._rescan_all)
        toolbar.addAction(self.rescan_action)

        self.duplicates_action = QAction("Find Duplicates…", self)
        self.duplicates_action.setShortcut(QKeySequence("Ctrl+D"))
        self.duplicates_action.triggered.connect(self._find_duplicates)
        toolbar.addAction(self.duplicates_action)

        toolbar.addSeparator()

        self.export_action = QAction("Export to Excel…", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self._export_xlsx)
        toolbar.addAction(self.export_action)

        self.export_backup_action = QAction("Backup…", self)
        self.export_backup_action.setShortcut(QKeySequence("Ctrl+B"))
        self.export_backup_action.triggered.connect(self._export_backup)
        toolbar.addAction(self.export_backup_action)

        self.import_backup_action = QAction("Restore…", self)
        self.import_backup_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_backup_action.triggered.connect(self._import_backup)
        toolbar.addAction(self.import_backup_action)

        self.stats_action = QAction("Stats", self)
        self.stats_action.triggered.connect(self._show_stats)
        toolbar.addAction(self.stats_action)

        toolbar.addSeparator()

        self.settings_action = QAction("Settings…", self)
        self.settings_action.triggered.connect(self._open_settings)
        toolbar.addAction(self.settings_action)

        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self._show_about)
        toolbar.addAction(self.about_action)

        # Central splitter: left filters | center table | right detail
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Filters panel
        filters = QWidget()
        f_layout = QVBoxLayout(filters)
        f_layout.addWidget(QLabel("Search"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Game name…")
        self.search_edit.textChanged.connect(self._proxy.set_search)
        f_layout.addWidget(self.search_edit)

        f_layout.addWidget(QLabel("Store"))
        self.store_combo = QComboBox()
        self.store_combo.addItems(["All", "Steam", "GOG", "Epic", "Other"])
        self.store_combo.currentTextChanged.connect(self._proxy.set_store)
        f_layout.addWidget(self.store_combo)

        f_layout.addWidget(QLabel("Status"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "ok", "not_found", "error", "pending"])
        self.status_combo.currentTextChanged.connect(self._proxy.set_status)
        f_layout.addWidget(self.status_combo)

        f_layout.addStretch(1)
        splitter.addWidget(filters)

        # Table
        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        # Default sort: alphabetical by game name (column 0, ascending).
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setItemDelegate(GamesItemDelegate(self.table))

        # Header: auto-resize columns to fit content (Excel-like "AutoFit").
        # stretchLastSection must be False so column widths are respected.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # Double-clicking a section divider auto-fits that column (built-in).
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_context_menu)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        # Detail panel
        self.detail = DetailPanel(self._db, self._model, self._image_cache, parent=self)
        self.detail.refetch_btn.clicked.connect(self._refetch_selected)
        splitter.addWidget(self.detail)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([180, 600, 400])
        self.setCentralWidget(splitter)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._copyright_lbl = QLabel("© 2026 Stavros Antoniou")
        self._copyright_lbl.setStyleSheet("color: #94A3B8; padding: 0 8px;")
        sb.addPermanentWidget(self._copyright_lbl)

    # ------------------------------------------------------------------ #
    # Data handling
    # ------------------------------------------------------------------ #
    def _refresh_table(self) -> None:
        records = list(self._db.all_records())
        self._model.set_records(records)
        self._auto_resize_columns()

    def _on_field_edited(self, folder_path: str, field: str, value: str) -> None:
        """Persist an inline table edit to the DB (called via model signal)."""
        try:
            self._db.set_field(folder_path, field, value)
        except ValueError as e:
            log.warning("Could not persist edit to %s.%s: %s", folder_path, field, e)
        except OSError as e:
            log.warning("DB error persisting edit to %s.%s: %s", folder_path, field, e)

    def _auto_resize_columns(self) -> None:
        """Resize all columns to fit their content (Excel-like AutoFit).

        Uses Qt's ``resizeColumnsToContents`` which sizes each column to the
        widest visible cell or header. We then enforce minimum widths so short
        columns (Status, Source) don't collapse too tight, and cap the
        Description column so it doesn't eat the whole table on long text.
        """
        self.table.resizeColumnsToContents()
        # (column index, minimum width, maximum width) — None = no limit
        constraints = {
            0: (120, 360),   # Game
            1: (60, 120),    # Platform
            2: (60, 120),    # Store
            3: (70, 200),    # Disk
            4: (80, 120),    # Released
            5: (50, 80),     # Rating
            6: (60, 120),    # ESRB
            7: (100, 260),   # Type
            8: (70, 120),    # Source
            9: (70, 110),    # Status
        }
        for col, (min_w, max_w) in constraints.items():
            current = self.table.columnWidth(col)
            if current < min_w:
                self.table.setColumnWidth(col, min_w)
            elif current > max_w:
                self.table.setColumnWidth(col, max_w)

    def _on_selection_changed(self, *_args) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.detail.set_record(None)
            return
        # Map proxy index -> source row
        proxy_index = indexes[0]
        source_index = self._proxy.mapToSource(proxy_index)
        row = source_index.row()
        record = self._model.record_at(row)
        self.detail.set_record(record, row=row)

    def _on_image_loaded(self, url: str, pixmap) -> None:
        self.detail.on_image_loaded(url, pixmap)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def _open_scan_dialog(self) -> None:
        dialog = ScanDialog(self._cataloger, self._config, parent=self)
        dialog.exec()
        # Refresh whatever happened (even dry-runs may have scanned folders)
        self._refresh_table()
        self._update_status_bar()

    def _add_game(self) -> None:
        """Manually add a game by name — no folder on disk required.

        Creates a GameRecord with a synthetic ``folder_path`` under
        ``/manual/<name>``, fetches metadata from the APIs synchronously, and
        selects the new row so the detail panel shows it immediately.
        """
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLineEdit,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Add Game")
        form = QFormLayout(dialog)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. Hollow Knight")
        form.addRow("Game name:", name_edit)

        platform_combo = QComboBox()
        platform_combo.addItems(["PC", "PC (Linux)", "PC (Fan Port)", "PC (Mod)"])
        form.addRow("Platform:", platform_combo)

        store_combo = QComboBox()
        store_combo.addItems(["Other", "Steam", "GOG", "Epic", "GOG / Steam"])
        form.addRow("Store:", store_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        # Pre-focus the name field and accept on Enter
        name_edit.setFocus()
        name_edit.returnPressed.connect(dialog.accept)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Add game", "Game name cannot be empty.")
            return

        # Build a synthetic record. folder_path must be unique; use /manual/<name>
        # so we can detect manual entries (no real folder to open).
        record = GameRecord(
            folder_name=name,
            folder_path=f"/manual/{name}",
            game_name=name,
            platform=platform_combo.currentText(),
            store=store_combo.currentText(),
            fetch_status="pending",
        )
        # Show a modal "Fetching…" dialog so the user knows the app is working
        # (the synchronous API call would otherwise freeze the window with no
        # feedback, looking like a hang on slow networks).
        from PySide6.QtWidgets import QProgressDialog
        progress = QProgressDialog(
            f"Fetching metadata for '{name}'…", None, 0, 0, self
        )
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        self.statusBar().showMessage(f"Adding '{name}'…")
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()  # paint the dialog before blocking
        try:
            record = self._cataloger._fetch(record)
        except Exception as e:  # noqa: BLE001 - last-resort guard to avoid UI crash
            record.fetch_status = "error"
            record.fetch_message = f"add game error: {e}"
        progress.close()
        if not record.store:
            record.store = "Other"
        self._db.upsert(record)

        self._refresh_table()
        self._update_status_bar()

        # Select the newly-added row so the detail panel shows it
        self._select_by_folder_path(record.folder_path)
        self.statusBar().showMessage(
            f"Added: {record.game_name} — {record.data_source or '?'} "
            f"{record.fetch_status}",
            5000,
        )

    def _select_by_folder_path(self, folder_path: str) -> None:
        """Find and select the row whose record.folder_path matches."""
        for row in range(self._model.rowCount()):
            rec = self._model.record_at(row)
            if rec and rec.folder_path == folder_path:
                proxy_index = self._proxy.mapFromSource(self._model.index(row, 0))
                if proxy_index.isValid():
                    self.table.selectRow(proxy_index.row())
                    self.table.scrollTo(proxy_index)
                return

    def _rescan_all(self) -> None:
        reply = QMessageBox.question(
            self, "Rescan all",
            "Re-fetch metadata for ALL games in the database?\n"
            "Your manual edits will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Use the scan dialog with rescan=True and the DB folder as root is
        # not applicable — instead we refetch each existing record directly.
        self._run_refetch_all()

    def _find_duplicates(self) -> None:
        """Open the Duplicates dialog to find and remove duplicate games."""
        records = list(self._db.all_records())
        dialog = DuplicatesDialog(records, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            removed = dialog.records_to_remove()
            if removed:
                with self._db.connect() as conn:
                    for rec in removed:
                        conn.execute(
                            "DELETE FROM games WHERE folder_path = ?;",
                            (rec.folder_path,),
                        )
                self._refresh_table()
                self._update_status_bar()
                self.detail.set_record(None)
                self.statusBar().showMessage(
                    f"Removed {len(removed)} duplicate game(s).", 5000
                )

    def _run_refetch_all(self) -> None:
        self._run_refetch(list(self._db.all_records()))

    def _run_refetch(self, records: list[GameRecord]) -> None:
        """Re-fetch metadata for *records* on a background thread.

        Shared by "Rescan All" and multi-row "Re-fetch selected". Single-row
        refetch stays synchronous (see ``_refetch_selected``) for instant
        detail-panel feedback; 2+ rows use this worker to avoid freezing the UI.
        """
        # Guard against concurrent refetch workers: a running worker would be
        # orphaned and could race on the DB / API clients.
        if getattr(self, "_refetch_worker", None) and self._refetch_worker.isRunning():
            QMessageBox.warning(
                self, "Busy",
                "A re-fetch is already running. Please wait for it to finish.",
            )
            return
        from PySide6.QtCore import QThread, Signal

        class RefetchWorker(QThread):
            progress = Signal(int, int, str)
            finished_summary = Signal(dict)

            def __init__(self_inner, cataloger, recs, parent=None):
                super().__init__(parent)
                self_inner._cataloger = cataloger
                self_inner._records = recs
                self_inner._cancelled = False

            def cancel(self_inner):
                self_inner._cancelled = True

            def run(self_inner):
                total = len(self_inner._records)
                ok = not_found = error = 0
                for idx, rec in enumerate(self_inner._records, 1):
                    if self_inner._cancelled:
                        break
                    try:
                        overrides = self_inner._cataloger.db.get_overrides(rec.folder_path)
                        rec.fetch_status = "pending"
                        rec = self_inner._cataloger._fetch(rec)
                        self_inner._cataloger._apply_overrides(rec, overrides)
                        if not rec.store:
                            rec.store = "Other"
                        self_inner._cataloger.db.upsert(rec)
                    except Exception as e:  # noqa: BLE001 - per-game guard
                        rec.fetch_status = "error"
                        rec.fetch_message = f"refetch error: {e}"
                        error += 1
                    else:
                        if rec.fetch_status == "ok":
                            ok += 1
                        elif rec.fetch_status == "not_found":
                            not_found += 1
                        else:
                            error += 1
                    self_inner.progress.emit(
                        idx, total,
                        f"{rec.data_source or '?'}: {rec.fetch_status} - {rec.game_name}",
                    )
                self_inner.finished_summary.emit(
                    {"ok": ok, "not_found": not_found, "error": error, "total": total}
                )

        self._refetch_worker = RefetchWorker(self._cataloger, records, parent=self)
        self._refetch_worker.progress.connect(self._on_refetch_progress)
        self._refetch_worker.finished_summary.connect(self._on_refetch_finished)
        # Self-cleanup: delete the QThread when done so old workers don't linger.
        self._refetch_worker.finished.connect(self._refetch_worker.deleteLater)
        self._refetch_worker.start()

    def _on_refetch_progress(self, idx: int, total: int, message: str) -> None:
        self.statusBar().showMessage(f"[{idx}/{total}] {message}")

    def _on_refetch_finished(self, summary: dict) -> None:
        self._refresh_table()
        self._update_status_bar()
        QMessageBox.information(
            self, "Rescan complete",
            f"Re-fetched {summary.get('total', 0)} games:\n"
            f"  OK: {summary.get('ok', 0)}\n"
            f"  Not found: {summary.get('not_found', 0)}\n"
            f"  Errors: {summary.get('error', 0)}",
        )

    def _refetch_selected(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        # Gather selected records (proxy → source row).
        records: list[GameRecord] = []
        rows: list[int] = []
        for proxy_index in indexes:
            row = self._proxy.mapToSource(proxy_index).row()
            rec = self._model.record_at(row)
            if rec is not None:
                records.append(rec)
                rows.append(row)
        if not records:
            return
        # Single row: synchronous (fast, updates detail panel immediately).
        if len(records) == 1:
            record = records[0]
            row = rows[0]
            overrides = self._db.get_overrides(record.folder_path)
            record.fetch_status = "pending"
            record = self._cataloger._fetch(record)
            self._cataloger._apply_overrides(record, overrides)
            if not record.store:
                record.store = "Other"
            self._db.upsert(record)
            self._model.update_record(row, record)
            self.detail.set_record(record, row=row)
            self._update_status_bar()
            self.statusBar().showMessage(
                f"Re-fetched: {record.data_source or '?'} {record.fetch_status}",
                4000,
            )
        else:
            # Multiple rows: background worker with progress in status bar.
            self._run_refetch(records)

    def _export_xlsx(self) -> None:
        default_name = str(Path(self._config.db_path).with_suffix(".xlsx"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", default_name,
            "Excel workbook (*.xlsx)",
        )
        if not path:
            return
        try:
            out = export_xlsx(self._db, path)
            QMessageBox.information(self, "Exported", f"Saved {self._db.count()} games to:\n{out}")
        except OSError as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _export_backup(self) -> None:
        """Export the full catalog to a compressed JSON backup (``.json.gz``)."""
        default_name = str(Path(self._config.db_path).with_suffix(".json.gz"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup Catalog", default_name,
            "Compressed JSON backup (*.json.gz)",
        )
        if not path:
            return
        try:
            out = export_backup(self._db, path)
            QMessageBox.information(
                self, "Backup created",
                f"Saved {self._db.count()} games to:\n{out}",
            )
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Backup failed", str(e))

    def _import_backup(self) -> None:
        """Restore a catalog from a compressed JSON backup.

        Asks the user whether to merge (upsert by ``folder_path``) or
        replace the entire catalog with the backup contents.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Catalog from Backup", "",
            "Compressed JSON backup (*.json.gz);;All files (*.*)",
        )
        if not path:
            return
        existing = self._db.count()
        if existing > 0:
            choice = QMessageBox.question(
                self, "Restore mode",
                f"The catalog already has {existing} game(s).\n\n"
                "Yes = Replace all (delete existing rows first)\n"
                "No   = Merge (upsert by folder path — keep rows not in the backup)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return
            replace_all = choice == QMessageBox.StandardButton.Yes
        else:
            replace_all = False
        try:
            summary = import_backup(self._db, path, replace_all=replace_all)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Restore failed", str(e))
            return
        mode = "Replaced" if replace_all else "Merged"
        QMessageBox.information(
            self, "Restore complete",
            f"{mode} {summary['imported']} game(s) "
            f"(format v{summary['format_version']}, "
            f"app v{summary['app_version']}).\n"
            f"{summary['skipped']} row(s) skipped.",
        )
        self._refresh_table()

    def _show_stats(self) -> None:
        stats = self._db.stats()
        dialog = StatsDialog(stats, parent=self)
        dialog.exec()

    def _show_about(self) -> None:
        dialog = AboutDialog(parent=self)
        dialog.exec()

    def _open_settings(self) -> None:
        # Guard against swapping API clients while a worker thread is mid-scan.
        if getattr(self, "_refetch_worker", None) and self._refetch_worker.isRunning():
            QMessageBox.warning(
                self, "Busy",
                "A re-fetch is running. Please wait for it to finish before "
                "changing settings.",
            )
            return
        dialog = SettingsDialog(self._config, parent=self)
        if dialog.exec():
            # Close old clients to release pooled connections before replacing.
            from ..rawg_client import RAWGClient
            from ..thegamesdb_client import TheGamesDBClient
            try:
                self._cataloger.rawg.close()
            except OSError as e:
                log.debug("rawg.close(): %s", e)
            try:
                self._cataloger.tgdb.close()
            except OSError as e:
                log.debug("tgdb.close(): %s", e)
            self._cataloger.rawg = RAWGClient(self._config)
            self._cataloger.tgdb = TheGamesDBClient(self._config)
            self._update_status_bar()

    # ------------------------------------------------------------------ #
    # Context menu
    # ------------------------------------------------------------------ #
    def _header_context_menu(self, pos) -> None:
        """Right-click menu on the column header — Excel-like auto-fit options."""
        from PySide6.QtWidgets import QMenu
        header = self.table.horizontalHeader()
        menu = QMenu(self)
        menu.addAction("Auto-fit all columns", self._auto_resize_columns)
        auto_fit_col = menu.addAction("Auto-fit this column")
        menu.addSeparator()
        menu.addAction("Reset to default widths", self._reset_column_widths)
        action = menu.exec(header.mapToGlobal(pos))
        if action == auto_fit_col:
            col = header.logicalIndexAt(pos)
            if col >= 0:
                self.table.resizeColumnToContents(col)

    def _reset_column_widths(self) -> None:
        """Restore reasonable default column widths."""
        defaults = {0: 280, 1: 80, 2: 80, 3: 120, 4: 100, 5: 70, 6: 90, 7: 180, 8: 90, 9: 90}
        for col, width in defaults.items():
            self.table.setColumnWidth(col, width)

    def _context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        # If the right-clicked row is already in the selection, operate on the
        # whole selection (multi-row actions). Otherwise select just this row.
        selected_rows = self.table.selectionModel().selectedRows()
        if not any(idx.row() == index.row() for idx in selected_rows):
            self.table.selectRow(index.row())
            selected_rows = self.table.selectionModel().selectedRows()
        records: list[GameRecord] = []
        for idx in selected_rows:
            row = self._proxy.mapToSource(idx).row()
            rec = self._model.record_at(row)
            if rec is not None:
                records.append(rec)
        if not records:
            return
        n = len(records)

        menu = QMenu(self)
        refetch_action = menu.addAction(
            "Re-fetch metadata" if n == 1 else f"Re-fetch {n} games"
        )
        open_folder_action = None
        if n == 1 and not records[0].folder_path.startswith("/manual/"):
            file_manager = "Explorer" if sys.platform == "win32" else "Files"
            open_folder_action = menu.addAction(f"Open folder in {file_manager}")
        menu.addSeparator()
        delete_action = menu.addAction(
            "Delete from catalog…" if n == 1 else f"Delete {n} games…"
        )
        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == refetch_action:
            self._refetch_selected()
        elif open_folder_action is not None and action == open_folder_action:
            self._open_folder(records[0])
        elif action == delete_action:
            self._delete_records(records)

    def _open_folder(self, record: GameRecord) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = record.folder_path
        if path.startswith("/manual/"):
            QMessageBox.information(
                self, "Manual entry",
                f"'{record.game_name or record.folder_name}' was added manually "
                f"and has no folder on disk.",
            )
            return
        if Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Folder missing", f"Path does not exist:\n{path}")

    def _delete_records(self, records: list[GameRecord]) -> None:
        n = len(records)
        if n == 0:
            return
        names = ", ".join(
            (r.game_name or r.folder_name) for r in records[:5]
        )
        suffix = "…" if n > 5 else ""
        reply = QMessageBox.question(
            self, "Delete game" if n == 1 else f"Delete {n} games",
            f"Remove {'this game' if n == 1 else f'these {n} games'} from the catalog?\n"
            f"{names}{suffix}\n\n(The folders on disk are not touched.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        with self._db.connect() as conn:
            for rec in records:
                conn.execute(
                    "DELETE FROM games WHERE folder_path = ?;", (rec.folder_path,)
                )
        self._refresh_table()
        self._update_status_bar()
        self.detail.set_record(None)

    # ------------------------------------------------------------------ #
    def _update_status_bar(self) -> None:
        total = self._db.count()
        stats = self._db.stats()
        ok = stats["by_status"].get("ok", 0)
        not_found = stats["by_status"].get("not_found", 0)
        error = stats["by_status"].get("error", 0)
        rawg = "RAWG: on" if self._cataloger.rawg.is_available() else "RAWG: off"
        tgdb_client = self._cataloger.tgdb
        if tgdb_client.is_available():
            q = tgdb_client.quota_info()
            rem = q["remaining"]
            limit = q["monthly_limit"]
            if rem is not None:
                tgdb = f"TGDB: {rem}/{limit}"
                tip = f"TheGamesDB — {rem}/{limit} requests remaining this month"
                reset = q.get("reset_seconds")
                if reset is not None:
                    tip += f" (resets in {self._fmt_duration(reset)})"
                if rem == 0:
                    tip += " — quota exhausted; wait for reset or use RAWG fallback"
            else:
                tgdb = "TGDB: on"
                tip = "TheGamesDB — quota not yet fetched"
        else:
            tgdb = "TGDB: off"
            tip = "TheGamesDB — API key not configured"
        self.statusBar().showMessage(
            f"{total} games | {ok} ok | {not_found} not found | {error} errors | "
            f"{tgdb} (primary) | {rawg} (fallback)"
        )
        # Tooltip with full quota details (hover the status bar to see it)
        sb = self.statusBar()
        sb.setToolTip(tip)

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        """Format a duration in seconds as a human-readable string."""
        s = int(seconds)
        days, s = divmod(s, 86400)
        hours, s = divmod(s, 3600)
        mins, s = divmod(s, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if mins:
            parts.append(f"{mins}m")
        parts.append(f"{s}s")
        return " ".join(parts)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:
        # Stop any running worker threads before exit
        worker = getattr(self, "_refetch_worker", None)
        if worker and worker.isRunning():
            worker.cancel()
            worker.wait(3000)
        quota_worker = getattr(self, "_quota_worker", None)
        if quota_worker and quota_worker.isRunning():
            quota_worker.wait(3000)
        event.accept()
