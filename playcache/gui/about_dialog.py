"""About dialog with app info and copyright notice."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..__init__ import __version__
from .theme import (
    ACCENT_LIGHT,
    BG_CARD,
    BG_HOVER,
    BG_WINDOW,
    BORDER,
    TEXT_MUTED,
    TEXT_PRIMARY,
)

AUTHOR = "Stavros Antoniou"
COPYRIGHT_YEAR = "2026"
COPYRIGHT = f"Copyright (c) {COPYRIGHT_YEAR} {AUTHOR}"

ABOUT_QSS = f"""
QDialog {{
    background-color: {BG_WINDOW};
}}
QLabel {{
    color: {TEXT_PRIMARY};
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


class AboutDialog(QDialog):
    """Polished About dialog with app icon, name, version, and copyright."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("About PlayCache")
        self.setMinimumWidth(380)
        self.setStyleSheet(ABOUT_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # App icon
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "app.png"
        if icon_path.is_file():
            icon_lbl = QLabel()
            pix = QPixmap(str(icon_path))
            if not pix.isNull():
                icon_lbl.setPixmap(
                    pix.scaled(
                        96, 96,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_lbl)

        # App name
        name_lbl = QLabel("PlayCache")
        name_font = QFont()
        name_font.setPointSize(20)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet(f"color: {ACCENT_LIGHT};")
        layout.addWidget(name_lbl)

        # Version
        ver_lbl = QLabel(f"Version {__version__}")
        ver_font = QFont()
        ver_font.setPointSize(10)
        ver_lbl.setFont(ver_font)
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(ver_lbl)

        # Spacer
        layout.addSpacing(8)

        # Tagline
        tagline_lbl = QLabel("A desktop game library cataloguer.")
        tagline_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline_lbl.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(tagline_lbl)

        layout.addSpacing(6)

        # Copyright
        copyright_lbl = QLabel(COPYRIGHT)
        copy_font = QFont()
        copy_font.setPointSize(9)
        copyright_lbl.setFont(copy_font)
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_lbl.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(copyright_lbl)

        # "All rights reserved"
        rights_lbl = QLabel("All rights reserved.")
        rights_lbl.setFont(copy_font)
        rights_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rights_lbl.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(rights_lbl)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
