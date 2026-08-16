"""Centralized dark theme stylesheet and smart color helpers for PlayCache.

All dark-theme colors live here so the palette is consistent across the
main window, table, filters, detail panel, and dialogs.

Color philosophy (slate-based, eye-friendly):
- Backgrounds use a cool slate gradient (darker for the window, slightly
  lighter for cards/panels) — reduces eye strain vs. pure black.
- Text uses gray-50 (near-white) for primary content and gray-400 for
  secondary/muted text — both exceed WCAG AA contrast on their backgrounds.
- Accent colors are vibrant (indigo/sky/emerald) so they pop on the dark
  background without being harsh.
- Table rows use zebra striping with a very subtle contrast (slate-800 vs
  slate-750) so rows are distinguishable but not distracting.
- Status cells get semantic coloring (green/amber/red) so the user can
  scan scan results at a glance.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

# --- Core palette ----------------------------------------------------------
BG_WINDOW = "#1F2937"        # slate-800 — main window background
BG_PANEL = "#283548"         # slate-750 — side panels / splitter children
BG_CARD = "#374151"          # slate-700 — cards, inputs, headers
BG_CARD_ALT = "#334155"     # slate-700 variant — zebra stripe alternate
BG_INPUT = "#1E293B"         # slate-900 — text fields (darker for focus)
BG_HOVER = "#3B4D63"         # slate-600 — hover states
BG_SELECTED = "#3730A3"      # indigo-800 — selected row (dark indigo)
BG_SELECTED_ALT = "#312E81"  # indigo-900 — selected zebra row

BORDER = "#475569"           # slate-600 — borders / separators
BORDER_LIGHT = "#334155"     # slate-700 — subtle inner borders

TEXT_PRIMARY = "#F1F5F9"     # slate-100 — primary text
TEXT_SECONDARY = "#CBD5E1"   # slate-300 — secondary text
TEXT_MUTED = "#94A3B8"       # slate-400 — muted / placeholder
TEXT_DISABLED = "#64748B"    # slate-500 — disabled

ACCENT = "#6366F1"           # indigo-500 — primary accent
ACCENT_LIGHT = "#818CF8"     # indigo-400 — hover / focus accent
ACCENT_BRIGHT = "#A5B4FC"    # indigo-300 — bright accent for highlights

# --- Status semantic colors (used in table cells + bar charts) -------------
STATUS_OK = "#22C55E"           # green-500
STATUS_NOT_FOUND = "#F59E0B"    # amber-500
STATUS_ERROR = "#EF4444"         # red-500
STATUS_PENDING = "#3B82F6"      # blue-500
STATUS_NONE = "#64748B"         # slate-500

STATUS_COLORS: dict[str, str] = {
    "ok": STATUS_OK,
    "not_found": STATUS_NOT_FOUND,
    "error": STATUS_ERROR,
    "pending": STATUS_PENDING,
    "(none)": STATUS_NONE,
}


# --- Smart text color (WCAG luminance) -------------------------------------
def _luminance(color: QColor) -> float:
    """WCAG relative luminance (0=black, 1=white)."""
    def _ch(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = _ch(color.red()), _ch(color.green()), _ch(color.blue())
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_text(bg_hex: str) -> QColor:
    """Return white or near-black text for the best contrast on ``bg_hex``.

    Crossover at luminance ~0.20 (the mathematical equality point of the
    two contrast ratios). Dark fills get white text; light fills get
    dark slate text. Guarantees WCAG AA (4.5:1) wherever possible.
    """
    bg = QColor(bg_hex)
    if not bg.isValid():
        return QColor("#FFFFFF")
    return QColor("#0F172A") if _luminance(bg) > 0.20 else QColor("#FFFFFF")


# --- Stylesheet ------------------------------------------------------------
DARK_QSS = f"""
/* ---- Global ---- */
QMainWindow, QDialog {{
    background-color: {BG_WINDOW};
    color: {TEXT_PRIMARY};
}}
QWidget {{
    background: transparent;
    color: {TEXT_PRIMARY};
}}
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}

/* ---- Toolbar ---- */
QToolBar {{
    background-color: {BG_PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
    spacing: 4px;
    padding: 4px;
}}
QToolBar QToolButton {{
    color: {TEXT_SECONDARY};
    background: transparent;
    border: none;
    padding: 6px 12px;
    border-radius: 4px;
}}
QToolBar QToolButton:hover {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}
QToolBar QToolButton:checked {{
    background-color: {ACCENT};
    color: white;
}}

/* ---- Splitter ---- */
QSplitter::handle {{
    background-color: {BORDER_LIGHT};
}}
QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

/* ---- Filters panel ---- */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 8px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border-color: {ACCENT_LIGHT};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
    border-color: {ACCENT};
    background-color: {BG_CARD};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: white;
}}
QComboBox::item:selected {{
    background-color: {ACCENT};
    color: white;
}}

/* ---- Table ---- */
QTableView {{
    background-color: {BG_WINDOW};
    alternate-background-color: {BG_CARD_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 4px;
    gridline-color: {BORDER_LIGHT};
    selection-background-color: {BG_SELECTED};
    selection-color: {TEXT_PRIMARY};
}}
QTableView::item {{
    padding: 4px 8px;
    border: none;
}}
QTableView::item:alternate {{
    background-color: {BG_CARD_ALT};
}}
QTableView::item:selected {{
    background-color: {BG_SELECTED};
}}
QTableView::item:selected:alternate {{
    background-color: {BG_SELECTED_ALT};
}}
QHeaderView::section {{
    background-color: {BG_CARD};
    color: {TEXT_SECONDARY};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {BORDER_LIGHT};
    border-bottom: 1px solid {BORDER};
    font-weight: bold;
}}
QHeaderView::section:hover {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}
QTableCornerButton::section {{
    background-color: {BG_CARD};
    border: none;
    border-bottom: 1px solid {BORDER};
}}

/* ---- Detail panel ---- */
QTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
}}
QTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ---- Buttons ---- */
QPushButton {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 64px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT_LIGHT};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
    color: white;
}}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
    background-color: {BG_PANEL};
    border-color: {BORDER_LIGHT};
}}

/* ---- Scroll bar ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---- Status bar ---- */
QStatusBar {{
    background-color: {BG_PANEL};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER_LIGHT};
}}
QStatusBar QLabel {{
    color: {TEXT_MUTED};
    padding: 0 4px;
}}

/* ---- Menu ---- */
QMenu {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER_LIGHT};
    margin: 4px 8px;
}}

/* ---- Group box ---- */
QGroupBox {{
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}

/* ---- Check box ---- */
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background-color: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ---- Progress bar ---- */
QProgressBar {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    color: {TEXT_PRIMARY};
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}
"""
