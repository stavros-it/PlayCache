"""Table model exposing GameRecord rows to Qt's model/view framework."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from ..models import GameRecord

# (header, record attribute, editable?)
COLUMNS = [
    ("Game",            "game_name",              True),
    ("Platform",        "platform",               True),
    ("Store",          "store",                  True),
    ("Disk",           "disk",                   False),
    ("Released",       "release_date_display",   False),
    ("Rating",         "user_rating",            True),
    ("ESRB",           "esrb_rating",            False),
    ("Type",           "game_type",              True),
    ("Source",         "data_source",             False),
    ("Status",         "fetch_status",           False),
]


class GamesTableModel(QAbstractTableModel):
    """Holds a list of GameRecord and exposes them to QTableView."""

    # Emitted when the user edits a cell: (folder_path, field_name, new_value)
    fieldEdited = Signal(str, str, str)

    def __init__(self, records: list[GameRecord] | None = None, parent=None):
        super().__init__(parent)
        self._records: list[GameRecord] = records or []

    # ------------------------------------------------------------------ #
    # Data access
    # ------------------------------------------------------------------ #
    def records(self) -> list[GameRecord]:
        return list(self._records)

    def set_records(self, records: list[GameRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def record_at(self, row: int) -> GameRecord | None:
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def update_record(self, row: int, record: GameRecord) -> None:
        if 0 <= row < len(self._records):
            self._records[row] = record
            idx = self.index(row, 0)
            bottom_right = self.index(row, len(COLUMNS) - 1)
            self.dataChanged.emit(idx, bottom_right, [Qt.ItemDataRole.DisplayRole,
                                                      Qt.ItemDataRole.EditRole,
                                                      Qt.ItemDataRole.ToolTipRole])

    # ------------------------------------------------------------------ #
    # QAbstractTableModel interface
    # ------------------------------------------------------------------ #
    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if (parent and parent.isValid()) else len(self._records)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if (parent and parent.isValid()) else len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        rec = self.record_at(index.row())
        if rec is None:
            return None
        _, attr, _ = COLUMNS[index.column()]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            value = getattr(rec, attr, "") or ""
            return str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = f"{rec.game_name}\n{rec.folder_path}"
            if rec.fetch_message:
                tip += f"\n{rec.fetch_message}"
            return tip
        if role == Qt.ItemDataRole.UserRole:
            # Expose the whole record so views/panels can fetch it by row
            return rec
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        _, attr, editable = COLUMNS[index.column()]
        if not editable:
            return False
        rec = self.record_at(index.row())
        if rec is None:
            return False
        new_value = value if isinstance(value, str) else str(value)
        setattr(rec, attr, new_value)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole,
                                              Qt.ItemDataRole.EditRole])
        # Persist the edit to the DB so it survives a table refresh.
        if rec.folder_path:
            self.fieldEdited.emit(rec.folder_path, attr, new_value)
        return True

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(COLUMNS):
            return COLUMNS[section][0]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        editable = COLUMNS[index.column()][2]
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags
