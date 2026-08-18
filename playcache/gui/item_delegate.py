"""Custom item delegate for the games table — smart status-based coloring.

The ``Status`` column gets a colored badge (green/amber/red/blue) with
smart contrast text (white on dark colors, dark on light colors) so the
user can scan scan results at a glance. All other columns use the
theme's default text color.
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QStyledItemDelegate

from .table_model import COLUMNS
from .theme import (
    BG_CARD_ALT,
    BG_SELECTED,
    BG_WINDOW,
    STATUS_COLORS,
    TEXT_PRIMARY,
    contrast_text,
)

_STATUS_COL = next(i for i, (h, _, _) in enumerate(COLUMNS) if h == "Status")
_SOURCE_COL = next(i for i, (h, _, _) in enumerate(COLUMNS) if h == "Source")


_SOURCE_COLORS = {
    "thegamesdb": "#818CF8",
    "rawg": "#38BDF8",
}


def _status_color(status: str) -> str:
    """Return the semantic color for a fetch_status value."""
    if not status:
        return STATUS_COLORS["(none)"]
    return STATUS_COLORS.get(status, STATUS_COLORS["(none)"])


class GamesItemDelegate(QStyledItemDelegate):
    """Item delegate that renders the Status column as a colored badge.

    Other columns are rendered by the default delegate (which respects the
    stylesheet's zebra striping and selection colors).
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        col = index.column()
        if col == _STATUS_COL:
            self._paint_status(painter, option, index)
            return
        if col == _SOURCE_COL:
            self._paint_source(painter, option, index)
            return
        # Default rendering for all other columns
        super().paint(painter, option, index)

    def _paint_status(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """Render the Status cell as a rounded badge with smart contrast text."""
        status = index.data(Qt.ItemDataRole.DisplayRole) or ""
        color_hex = _status_color(status)
        text_color = contrast_text(color_hex)

        rect = option.rect
        # Check if this row is selected (for background)
        is_selected = bool(option.state & QStyle.State_Selected)
        is_alternate = bool(option.features & QStyleOptionViewItem.ViewItemFeature.Alternate)

        # Draw the cell background (zebra or selected)
        painter.save()
        if is_selected:
            painter.fillRect(rect, QColor(BG_SELECTED))
        elif is_alternate:
            painter.fillRect(rect, QColor(BG_CARD_ALT))
        else:
            painter.fillRect(rect, QColor(BG_WINDOW))

        # Draw the badge: a rounded rect inside the cell with padding
        badge_h = max(0, min(rect.height() - 8, 20))
        badge_w = min(rect.width() - 12, 90)
        badge_x = rect.x() + (rect.width() - badge_w) // 2
        badge_y = rect.y() + (rect.height() - badge_h) // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        # Draw the status text inside the badge
        painter.setPen(text_color)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            badge_rect,
            Qt.AlignmentFlag.AlignCenter,
            status or "—",
        )
        painter.restore()

    def _paint_source(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """Render the Source column with a subtle colored text."""
        source = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.rect
        is_selected = bool(option.state & QStyle.State_Selected)
        is_alternate = bool(option.features & QStyleOptionViewItem.ViewItemFeature.Alternate)

        painter.save()
        # Background
        if is_selected:
            painter.fillRect(rect, QColor(BG_SELECTED))
        elif is_alternate:
            painter.fillRect(rect, QColor(BG_CARD_ALT))
        else:
            painter.fillRect(rect, QColor(BG_WINDOW))

        text_color = QColor(_SOURCE_COLORS.get(source, TEXT_PRIMARY))

        painter.setPen(text_color)
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(
            rect.adjusted(8, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            source or "—",
        )
        painter.restore()
