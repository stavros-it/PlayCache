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

import warnings

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyleOptionViewItem,
)

from playcache.gui.item_delegate import GamesItemDelegate
from playcache.gui.table_model import COLUMNS, GamesTableModel
from playcache.models import GameRecord


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


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


@pytest.mark.filterwarnings("ignore")
@pytest.mark.parametrize("col_name", [c[0] for c in COLUMNS])
def test_paint_does_not_raise_for_any_column(qapp, col_name):
    """Painting every column (including Status and Source) must not throw."""
    model = GamesTableModel([_sample_record()])
    delegate = GamesItemDelegate()
    col = next(i for i, c in enumerate(COLUMNS) if c[0] == col_name)
    index = model.index(0, col)

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


@pytest.mark.filterwarnings("ignore")
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


@pytest.mark.filterwarnings("ignore")
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


@pytest.mark.filterwarnings("ignore")
def test_paint_selected_and_alternate_combinations(qapp):
    """All four state/alternate combinations paint without error."""
    model = GamesTableModel([_sample_record()])
    delegate = GamesItemDelegate()
    status_col = next(i for i, c in enumerate(COLUMNS) if c[0] == "Status")
    source_col = next(i for i, c in enumerate(COLUMNS) if c[0] == "Source")
    index_status = model.index(0, status_col)
    index_source = model.index(0, source_col)

    pixmap = QPixmap(200, 40)
    painter = QPainter(pixmap)
    try:
        for selected in (False, True):
            for alt in (False, True):
                state = QStyle.State(QStyle.State_Enabled)
                if selected:
                    state |= QStyle.State_Selected
                delegate.paint(painter, _option(state, alternate=alt), index_status)
                delegate.paint(painter, _option(state, alternate=alt), index_source)
    finally:
        painter.end()
