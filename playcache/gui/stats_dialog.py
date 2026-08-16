"""Polished statistics dialog with metric cards and bar charts (dark theme).

Everything is data-driven: metric cards and distribution sections are built
from declarative lists, so adding a new stat to ``db.stats()`` only requires
adding one entry to ``METRIC_CARDS`` or ``DISTRIBUTIONS``. Grid positions and
card row wrapping are computed dynamically.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    ACCENT,
    ACCENT_LIGHT,
    BG_CARD,
    BG_HOVER,
    BG_WINDOW,
    BORDER,
    STATUS_COLORS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    contrast_text,
)

# Local aliases for the bar chart (track color is the unfilled bar background)
TRACK = BORDER  # slate-600 — same hue as borders, looks like an empty track

# --- Declarative data: drives all UI construction ---------------------------

# Metric cards: (getter, label, accent_color).
# Getters receive the full stats dict and return an int.
METRIC_CARDS: list[tuple] = [
    (lambda s: s.get("total", 0), "Total games", ACCENT_LIGHT),
    (lambda s: s.get("by_status", {}).get("ok", 0), "With metadata", STATUS_COLORS["ok"]),
    (lambda s: s.get("completeness", {}).get("with_cover", 0), "With cover art", "#38BDF8"),
    (lambda s: s.get("completeness", {}).get("with_release", 0), "With release date", "#A78BFA"),
    (lambda s: s.get("completeness", {}).get("with_rating", 0), "With user rating", "#FBBF24"),
    (lambda s: s.get("completeness", {}).get("with_esrb", 0), "With ESRB rating", "#F87171"),
    (lambda s: s.get("completeness", {}).get("with_metacritic", 0), "With Metacritic", "#34D399"),
    (lambda s: s.get("completeness", {}).get("with_overrides", 0), "Manually edited", "#A78BFA"),
]

# Distribution sections: (stats_key, title, accent_color, use_status_colors).
# Grid positions are computed dynamically from this list.
DISTRIBUTIONS: list[tuple] = [
    ("by_status", "By status", ACCENT, True),
    ("by_source", "By data source", ACCENT, False),
    ("by_store", "By store", "#38BDF8", False),
    ("by_platform", "By platform", "#A78BFA", False),
    ("by_esrb", "By ESRB rating", "#F87171", False),
    ("by_disk", "By disk", "#34D399", False),
    ("by_year", "By release year", "#FBBF24", False),
]

# Number of metric cards per row (wraps automatically).
CARDS_PER_ROW = 4

# Number of columns in the distributions grid.
GRID_COLUMNS = 2

DIALOG_QSS = f"""
QDialog {{
    background-color: {BG_WINDOW};
}}
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QWidget {{
    background: transparent;
}}
QDialogButtonBox QPushButton {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 64px;
}}
QDialogButtonBox QPushButton:hover {{
    background-color: {BG_HOVER};
}}
"""


class BarChart(QWidget):
    """Horizontal bar chart with in-bar labels and numbers.

    The chart fills all available vertical space (via ``Expanding`` size
    policy), distributing bars evenly. This avoids large gaps when a
    chart with few entries sits in a grid row alongside a taller chart.

    When ``use_status_colors`` is True, bars are colored per-label via
    ``STATUS_COLORS`` (falling back to ``color``). Otherwise all bars use
    ``color`` — this prevents a non-status section from accidentally
    picking up status colors if a label happens to match a status key.

    Text color inside each bar is chosen automatically based on the fill
    color's luminance: white on dark fills, near-black on light fills.
    """

    def __init__(
        self,
        data: list[tuple[str, int]],
        color: str = ACCENT,
        *,
        use_status_colors: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._data = data
        self._color = color
        self._use_status_colors = use_status_colors
        self._min_bar_h = 22
        self._max_bar_h = 32
        self._gap = 4
        rows = max(len(data), 1)
        self.setMinimumHeight(rows * (self._min_bar_h + self._gap) + 4)
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _event) -> None:
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        max_val = max((v for _, v in self._data), default=1) or 1
        w = self.width()
        h = self.height()
        n = len(self._data)

        gap = self._gap
        bar_h = min(self._max_bar_h, (h - gap * (n - 1) - 4) // n) if n > 0 else self._min_bar_h
        bar_h = max(bar_h, self._min_bar_h)
        total_h = bar_h * n + gap * (n - 1)
        y_start = (h - total_h) // 2
        pad = 10

        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()

        text_muted = QColor(TEXT_MUTED)
        track_color = QColor(TRACK)

        for i, (label, value) in enumerate(self._data):
            y = y_start + i * (bar_h + gap)
            fill_w = int(w * value / max_val) if max_val else 0

            # Track (full width)
            painter.setBrush(track_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(0, y, w, bar_h, 4, 4)

            # Fill
            fill_color_hex = self._color
            if fill_w > 0:
                if self._use_status_colors:
                    fill_color_hex = STATUS_COLORS.get(label, self._color)
                else:
                    fill_color_hex = self._color
                painter.setBrush(QColor(fill_color_hex))
                painter.drawRoundedRect(0, y, fill_w, bar_h, 4, 4)

            # Smart text color: white on dark fills, dark on light fills.
            in_bar_text = contrast_text(fill_color_hex) if fill_w > 0 else text_muted

            label_text = label
            value_text = str(value)
            label_w = fm.horizontalAdvance(label_text)
            value_w = fm.horizontalAdvance(value_text)

            both_fit = fill_w >= label_w + value_w + pad * 3
            value_fits = fill_w >= value_w + pad * 2

            if fill_w > 0 and both_fit:
                # Both inside the fill: label left, value right (with padding
                # from both edges so nothing touches the bar border).
                painter.setPen(in_bar_text)
                painter.drawText(
                    pad, y, fill_w - pad * 2 - value_w, bar_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label_text,
                )
                painter.drawText(
                    pad, y, fill_w - pad * 2, bar_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value_text,
                )
            elif fill_w > 0 and value_fits:
                # Value inside-right (in-bar color); label outside-right (muted)
                painter.setPen(in_bar_text)
                painter.drawText(
                    pad, y, fill_w - pad * 2, bar_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value_text,
                )
                painter.setPen(text_muted)
                painter.drawText(
                    fill_w + pad, y, w - fill_w - pad, bar_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label_text,
                )
            else:
                # Both outside the fill (muted), value right-aligned at bar end
                painter.setPen(text_muted)
                painter.drawText(
                    fill_w + pad, y, w - fill_w - pad, bar_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label_text,
                )
                painter.drawText(
                    0, y, w - pad, bar_h,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value_text,
                )


class _StatCard(QFrame):
    """A small metric card with a big number and a label beneath it."""

    def __init__(self, value: str | int, label: str, accent: str = ACCENT, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setStyleSheet(f"""
            #statCard {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-left: 4px solid {accent};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        value_lbl = QLabel(str(value))
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        value_lbl.setFont(font)
        value_lbl.setStyleSheet(f"color: {accent}; background: transparent; border: none;")
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(value_lbl)

        label_lbl = QLabel(label)
        small = QFont()
        small.setPointSize(8)
        label_lbl.setFont(small)
        label_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
        label_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label_lbl)


class _Section(QFrame):
    """A titled section containing a widget (e.g. a bar chart)."""

    def __init__(self, title: str, body: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("section")
        self.setStyleSheet(f"""
            #section {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        title_lbl.setFont(font)
        title_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; background: transparent; border: none;"
        )
        layout.addWidget(title_lbl)
        layout.addWidget(body, 1)


class StatsDialog(QDialog):
    """Library statistics overview with metric cards and bar charts.

    All UI is built dynamically from ``METRIC_CARDS`` and ``DISTRIBUTIONS``
    module-level lists, so new stats only require adding one entry there.
    Card rows wrap automatically at ``CARDS_PER_ROW``; grid positions are
    computed from the number of non-empty distributions.
    """

    def __init__(self, stats: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Library Statistics")
        self.setMinimumWidth(760)
        self.resize(820, 720)
        self.setStyleSheet(DIALOG_QSS)
        self._stats = stats
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(12)

        # --- Header ------------------------------------------------------
        outer.addLayout(self._build_header())

        # --- Metric cards (dynamic rows, wrapping at CARDS_PER_ROW) ------
        for row in self._card_rows():
            outer.addLayout(row)

        # --- Distributions grid (dynamic positions) ----------------------
        outer.addWidget(self._build_distributions_scroll(), 1)

        # --- Buttons -----------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel("Library Statistics")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        total = self._stats.get("total", 0)
        total_lbl = QLabel(f"{total:,} games")
        total_font = QFont()
        total_font.setPointSize(12)
        total_font.setBold(True)
        total_lbl.setFont(total_font)
        total_lbl.setStyleSheet(f"color: {ACCENT_LIGHT}; background: transparent;")
        header.addWidget(total_lbl)
        return header

    def _card_rows(self) -> list[QHBoxLayout]:
        """Build metric card rows, wrapping at ``CARDS_PER_ROW``."""
        rows: list[QHBoxLayout] = []
        current = QHBoxLayout()
        current.setSpacing(8)
        count = 0
        for getter, label, accent in METRIC_CARDS:
            value = getter(self._stats)
            current.addWidget(_StatCard(value, label, accent))
            count += 1
            if count >= CARDS_PER_ROW:
                current.addStretch()
                rows.append(current)
                current = QHBoxLayout()
                current.setSpacing(8)
                count = 0
        if count > 0:
            current.addStretch()
            rows.append(current)
        return rows

    def _build_distributions_scroll(self) -> QScrollArea:
        """Build the scrollable grid of distribution bar charts."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        # Collect non-empty distributions.
        sections: list[tuple[str, str, bool]] = []
        for key, title, color, use_sc in DISTRIBUTIONS:
            data = list(self._stats.get(key, {}).items())
            if data:
                sections.append((title, data, use_sc))

        # Place sections in the grid dynamically.
        # 2 columns; the last section spans both columns if the count is odd.
        for idx, (title, data, use_sc) in enumerate(sections):
            row = idx // GRID_COLUMNS
            col = idx % GRID_COLUMNS
            # Determine accent color from DISTRIBUTIONS (match by title).
            accent = ACCENT
            for _, d_title, d_color, _ in DISTRIBUTIONS:
                if d_title == title:
                    accent = d_color
                    break
            is_last = idx == len(sections) - 1
            if is_last and col != 0:
                # Odd number of sections: last one spans both columns.
                grid.addWidget(self._section(title, data, color=accent, use_status_colors=use_sc),
                               row, 0, 1, GRID_COLUMNS)
            else:
                grid.addWidget(self._section(title, data, color=accent, use_status_colors=use_sc),
                               row, col)

        scroll.setWidget(scroll_content)
        return scroll

    def _section(
        self,
        title: str,
        data: list[tuple[str, int]],
        color: str = ACCENT,
        *,
        use_status_colors: bool = False,
    ) -> _Section:
        chart = BarChart(data, color=color, use_status_colors=use_status_colors)
        return _Section(title, chart)
