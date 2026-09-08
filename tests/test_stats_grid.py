"""Regression test: stats distribution sections must never share a grid cell.

The "last section spans both columns" branch fired on
``is_last and col != 0`` — i.e. exactly when the section count is *even*,
where the previous section already occupies ``(row, 0)``, so two charts
were added to the same cell. With an even number of non-empty
distributions every section must occupy its own cell; with an odd number
the last section (alone at the start of its row) spans both columns.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings

import pytest
from PySide6.QtWidgets import QApplication, QGridLayout

from playcache.gui.stats_dialog import StatsDialog

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


def _base_stats() -> dict:
    return {
        "total": 10,
        "by_status": {"ok": 5, "(none)": 5},
        "by_source": {"rawg": 10},
        "by_store": {"Steam": 10},
        "by_platform": {"PC": 10},
        "by_esrb": {"(none)": 10},
        "by_disk": {"TOSHIBA 2TB": 10},
        "by_year": {"2023": 10},
        "completeness": {},
    }


def _cells_by_title(dialog: StatsDialog) -> dict[tuple[int, int], list[str]]:
    grids = [g for g in dialog.findChildren(QGridLayout) if g.count() >= 1]
    assert grids, "no distribution grid found"
    grid = max(grids, key=lambda g: g.count())
    cells: dict[tuple[int, int], list[str]] = {}
    for i in range(grid.count()):
        item = grid.itemAt(i)
        if item.widget() is None:
            continue
        row, col, row_span, col_span = grid.getItemPosition(i)
        title = item.widget().layout().itemAt(0).widget().text()
        for r in range(row, row + row_span):
            for c in range(col, col + col_span):
                cells.setdefault((r, c), []).append(title)
    return cells


def _assert_no_overlap(cells: dict[tuple[int, int], list[str]]) -> None:
    overlaps = {cell: titles for cell, titles in cells.items() if len(titles) > 1}
    assert overlaps == {}, f"sections share grid cells: {overlaps}"


def test_even_section_count_places_each_section_in_own_cell(qapp):
    stats = dict(_base_stats(), by_year={})
    dialog = StatsDialog(stats)
    cells = _cells_by_title(dialog)
    _assert_no_overlap(cells)
    titles = [title for titles in cells.values() for title in titles]
    assert len(titles) == 6
    assert cells[(2, 1)] == ["By disk"]
    assert cells[(2, 0)] == ["By ESRB rating"]


def test_odd_section_count_last_spans_both_columns(qapp):
    dialog = StatsDialog(_base_stats())
    cells = _cells_by_title(dialog)
    _assert_no_overlap(cells)
    titles = {title for titles in cells.values() for title in titles}
    assert len(titles) == 7
    assert cells[(3, 0)] == ["By release year"]
    assert cells[(3, 1)] == ["By release year"]


def test_single_section_spans_without_overlap(qapp):
    stats = {
        "total": 3,
        "by_status": {"ok": 3},
        "by_source": {},
        "by_store": {},
        "by_platform": {},
        "by_esrb": {},
        "by_disk": {},
        "by_year": {},
        "completeness": {},
    }
    dialog = StatsDialog(stats)
    cells = _cells_by_title(dialog)
    _assert_no_overlap(cells)
    assert cells[(0, 0)] == ["By status"]
    assert cells[(0, 1)] == ["By status"]
