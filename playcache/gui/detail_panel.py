"""Detail panel: shows full metadata for the selected game with editable fields."""
from __future__ import annotations

import logging
import urllib.parse

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..image_cache import ImageCache
from ..models import GameRecord
from .table_model import GamesTableModel
from .theme import BG_INPUT, TEXT_MUTED

log = logging.getLogger(__name__)

# (label, attribute, kind)  kind in {"text", "longtext", "number", "readonly"}
FIELDS = [
    ("Game",            "game_name",         "text"),
    ("Platform",        "platform",          "text"),
    ("Store",          "store",             "text"),
    ("Rating",         "user_rating",       "text"),
    ("Type",           "game_type",         "text"),
    ("Release date",   "release_date",      "text"),
    ("Developer",      "developer",         "text"),
    ("Publisher",      "publisher",         "text"),
    ("Website",        "website",           "text"),
    ("Description",    "short_description", "longtext"),
]

READONLY_FIELDS = [
    ("Folder",         "folder_name",       None),
    ("Path",           "folder_path",        None),
    ("ESRB",           "esrb_rating",        None),
    ("Metacritic",     "metacritic_score",  None),
    ("RAWG ID",        "rawg_id",            None),
    ("TheGamesDB ID",  "thegamesdb_id",     None),
    ("Source",         "data_source",        None),
    ("Status",         "fetch_status",       None),
    ("Message",        "fetch_message",     None),
]


class DetailPanel(QWidget):
    """Right-hand panel showing full metadata for the selected game."""

    def __init__(self, db: Database, model: GamesTableModel,
                 image_cache: ImageCache, parent: QWidget | None = None):
        super().__init__(parent)
        self._db = db
        self._model = model
        self._image_cache = image_cache
        self._record: GameRecord | None = None
        self._row: int = -1
        self._current_url: str = ""

        layout = QVBoxLayout(self)

        # Cover image
        self.cover_label = QLabel("No game selected")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(320, 180)
        self.cover_label.setStyleSheet(
            f"background-color: {BG_INPUT}; color: {TEXT_MUTED}; border-radius: 4px;"
        )
        self.cover_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # YouTube gameplay search button (below cover)
        self.youtube_btn = QPushButton("▶ Search YouTube Gameplay")
        self.youtube_btn.setStyleSheet(
            "QPushButton { background-color: #FF0000; color: white; "
            "border-radius: 4px; padding: 6px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #CC0000; }"
            "QPushButton:disabled { background-color: #555; color: #999; }"
        )
        self.youtube_btn.setEnabled(False)
        self.youtube_btn.clicked.connect(self._search_youtube)
        layout.addWidget(self.youtube_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Editable form
        self._inputs: dict[str, QLineEdit | QTextEdit | QSpinBox] = {}
        form = QFormLayout()
        for label, attr, kind in FIELDS:
            if kind == "longtext":
                w = QTextEdit()
                w.setFixedHeight(72)
            elif kind == "number":
                w = QSpinBox()
                w.setRange(0, 100)
                w.setSpecialValueText("—")
            else:
                w = QLineEdit()
            self._inputs[attr] = w
            form.addRow(label, w)
        layout.addLayout(form)

        # Read-only metadata
        readonly_label = QLabel("Metadata")
        readonly_label.setStyleSheet(
            f"font-weight: bold; margin-top: 8px; color: {TEXT_MUTED};"
        )
        layout.addWidget(readonly_label)
        self._readonly_labels: dict[str, QLabel] = {}
        ro_form = QFormLayout()
        for label, attr, _ in READONLY_FIELDS:
            value_label = QLabel("—")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._readonly_labels[attr] = value_label
            ro_form.addRow(label, value_label)
        layout.addLayout(ro_form)

        # Action buttons
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Changes")
        self.save_btn.clicked.connect(self._save)
        self.website_btn = QPushButton("Open Website")
        self.website_btn.clicked.connect(self._open_website)
        self.refetch_btn = QPushButton("Re-fetch")
        self.refetch_btn.setEnabled(False)  # wired by main window
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.website_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.refetch_btn)
        layout.addLayout(btn_row)

        layout.addStretch(1)

        # Disable inputs until a row is selected
        self._set_enabled(False)

    # ------------------------------------------------------------------ #
    def set_record(self, record: GameRecord | None, row: int = -1) -> None:
        """Populate the panel from ``record`` (or clear if None)."""
        self._record = record
        self._row = row
        if record is None:
            self.cover_label.setText("No game selected")
            self.cover_label.setPixmap(QPixmap())
            self._current_url = ""
            for w in self._inputs.values():
                if isinstance(w, QTextEdit):
                    w.clear()
                elif isinstance(w, QSpinBox):
                    w.setValue(0)
                else:
                    w.clear()
            for label in self._readonly_labels.values():
                label.setText("—")
            self._set_enabled(False)
            return

        self._set_enabled(True)
        for attr, w in self._inputs.items():
            value = getattr(record, attr, "")
            if isinstance(w, QTextEdit):
                w.setPlainText(str(value or ""))
            elif isinstance(w, QSpinBox):
                try:
                    w.setValue(int(value) if value not in (None, "") else 0)
                except (TypeError, ValueError):
                    w.setValue(0)
            else:
                w.setText(str(value or ""))

        for label, attr, _ in READONLY_FIELDS:
            value = getattr(record, attr, "")
            text = "—" if value in (None, "", 0) else str(value)
            self._readonly_labels[attr].setText(text)

        # Load cover image lazily
        url = record.cover_url or ""
        self._current_url = url
        if url:
            self.cover_label.setText("Loading…")
            self.cover_label.setPixmap(QPixmap())
            self._image_cache.request(url)
        else:
            self.cover_label.setText("No cover")
            self.cover_label.setPixmap(QPixmap())

    # ------------------------------------------------------------------ #
    def on_image_loaded(self, url: str, pixmap: QPixmap | None) -> None:
        """Slot connected to ImageCache.image_loaded."""
        if url != self._current_url or pixmap is None:
            return
        scaled = pixmap.scaled(
            self.cover_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cover_label.setPixmap(scaled)

    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        if self._record is None:
            return
        changes: dict[str, str] = {}
        for attr, w in self._inputs.items():
            if isinstance(w, QTextEdit):
                value = w.toPlainText()
            elif isinstance(w, QSpinBox):
                value = str(w.value()) if w.value() != 0 else ""
            else:
                value = w.text()
            if str(getattr(self._record, attr, "") or "") != value:
                changes[attr] = value

        if not changes:
            QMessageBox.information(self, "No changes", "No fields were changed.")
            return

        ok = True
        failed: list[str] = []
        succeeded: list[str] = []
        for attr, value in changes.items():
            try:
                if self._db.set_field(self._record.folder_path, attr, value):
                    succeeded.append(attr)
                else:
                    ok = False
                    failed.append(attr)
            except ValueError:
                ok = False
                failed.append(attr)
            except Exception as e:
                log.warning("DB error saving %s.%s: %s", self._record.folder_path, attr, e)
                ok = False
                failed.append(attr)

        for attr in succeeded:
            setattr(self._record, attr, changes[attr])
        if succeeded and self._row >= 0:
            self._model.update_record(self._row, self._record)

        if ok:
            QMessageBox.information(self, "Saved", f"Saved {len(succeeded)} field(s).")
        elif succeeded:
            QMessageBox.warning(
                self, "Partial save",
                f"Saved {len(succeeded)} field(s), but failed to save: "
                f"{', '.join(failed)}.",
            )
        else:
            QMessageBox.warning(
                self, "Save failed",
                f"Could not save any fields. Failed: {', '.join(failed)}.",
            )

    def _open_website(self) -> None:
        if self._record and self._record.website:
            QDesktopServices.openUrl(self._record.website)

    def _search_youtube(self) -> None:
        """Open YouTube search for '<game name> gameplay' in the default browser."""
        if not self._record:
            return
        query = (self._record.game_name or self._record.folder_name).strip()
        if not query:
            return
        encoded = urllib.parse.quote(f"{query} gameplay")
        QDesktopServices.openUrl(QUrl(f"https://www.youtube.com/results?search_query={encoded}"))

    def _set_enabled(self, enabled: bool) -> None:
        for w in self._inputs.values():
            w.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.refetch_btn.setEnabled(enabled)
        self.website_btn.setEnabled(enabled and bool(self._record and self._record.website))
        self.youtube_btn.setEnabled(enabled and bool(self._record))
