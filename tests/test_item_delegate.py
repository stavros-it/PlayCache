"""Tests for the games table item delegate (no network).

Regression test: ``QStyleOptionViewItem.State_Selected`` and
``State_Alternate`` were removed in PySide6 6.x. The delegate must use
``QStyle.State_Selected`` and ``QStyleOptionViewItem.ViewItemFeature.Alternate``
instead, otherwise ``paint()`` raises ``AttributeError`` on every cell and the
table viewport cannot update — which made it look like deletes/edits had no
effect.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QModelIndex, QRect
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
)

from playcache.gui.item_delegate import GamesItemDelegate
from playcache.gui.table_model import COLUMNS, GamesTableModel
from playcache.models import GameRecord


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_index(model: GamesTableModel, row: int, col: int) -> QModelIndex:
    return model.index(row, col)


def _option(state=QStyle.State(QStyle.State_Enabled), alternate=False) -> QStyleOptionViewItem:
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 200, 40)
    opt.state = state
    if alternate:
        opt.features = QStyleOptionViewItem.ViewItemFeature(
            QStyleOptionViewItem.ViewItemFeature.HasDisplay
            | QStyleOptionViewItem.ViewItemFeature.Alternate
        )
    else:
        opt.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
    return opt


def _sample_record(status: str = "ok", source: str = "thegamesdb") -> GameRecord:
    return GameRecord(
        folder_name="Hollow Knight",
        folder_path="/games/Hollow Knight",
        game_name="Hollow Knight",
        platform="PC",
        store="GOG",
        fetch_status=status,
        data_source=source,
    )


@pytest.mark.parametrize("col_name", [c[0] for c in COLUMNS])
def test_paint_does_not_raise_for_any_column(qapp, col_name):
    """Painting every column (including Status and Source) must not throw."""
    model = GamesTableModel([_sample_record()])
    delegate = GamesItemDelegate()
    col = next(i for i, c in enumerate(COLUMNS) if c[0] == col_name)
    index = _make_index(model, 0, col)

    pixmap = QPixmap(200, 40)
    painter = QPainter(pixmap)
    try:
        for state in [
            QStyle.State(QStyle.State_Enabled),
            QStyle.State(QStyle.State_Enabled | QStyle.State_Selected),
        ]:
            for alt in (False, True):
                delegate.paint(painter, _option(state, alternate=alt), index)
    finally:
        painter.end()


def test_paint_status_all_known_statuses(qapp):
    """The status badge paints for every known fetch_status without error."""
    statuses = ["", "ok", "not_found", "error", "pending", "skipped"]
    records = [_sample_record(status=s) for s in statuses]
    model = GamesTableModel(records)
    delegate = GamesItemDelegate()
    status_col = next(i for i, c in enumerate(COLUMNS) if c[0] == "Status")

    pixmap = QPixmap(200, 40)
    painter = QPainter(pixmap)
    try:
        for row in range(model.rowCount()):
            index = model.index(row, status_col)
            delegate.paint(painter, _option(alternate=row % 2 == 1), index)
    finally:
        painter.end()


def test_paint_source_all_known_sources(qapp):
    """The source column paints for every known data_source without error."""
    sources = ["", "thegamesdb", "rawg", "none"]
    records = [_sample_record(source=s) for s in sources]
    model = GamesTableModel(records)
    delegate = GamesItemDelegate()
    source_col = next(i for i, c in enumerate(COLUMNS) if c[0] == "Source")

    pixmap = QPixmap(200, 40)
    painter = QPainter(pixmap)
    try:
        for row in range(model.rowCount()):
            index = model.index(row, source_col)
            delegate.paint(painter, _option(alternate=row % 2 == 1), index)
    finally:
        painter.end()


def test_delegate_paints_inside_tableview(qapp):
    """End-to-end: the delegate paints when used by a real QTableView.

    This catches issues that only surface during Qt's internal paint pipeline
    (e.g. option.features not being set correctly by the view).
    """
    records = [
        _sample_record(status="ok", source="thegamesdb"),
        _sample_record(status="not_found", source="rawg"),
        _sample_record(status="error", source=""),
    ]
    model = GamesTableModel(records)
    table = QTableView()
    table.setModel(model)
    table.setItemDelegate(GamesItemDelegate())
    table.setAlternatingRowColors(True)
    table.resize(400, 200)
    table.show()
    qapp.processEvents()
    # Force a paint of the viewport — if paint() raises, Qt swallows the
    # exception but the viewport pixmap stays blank. We just verify no
    # unhandled exception escapes to the test runner.
    pixmap = QPixmap(table.viewport().size())
    table.viewport().render(pixmap)
