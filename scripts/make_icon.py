"""Generate the PlayCache application icon.

Renders a stylized **gamepad** (controller) silhouette inside a vault dial —
clearly "games" (not a video player). Writes:
  - playcache/assets/app.png   (256x256, for reference / Linux / docs)
  - playcache/assets/app.ico   (multi-resolution: 16,32,48,64,128,256)

Design: a deep-indigo rounded square (the vault) with a white circle
containing an indigo gamepad silhouette — two grips, a D-pad on the left,
two action buttons (A/B) on the right, and a center home/menu dot.

Run:  python scripts/make_icon.py
"""
from __future__ import annotations

import io
from pathlib import Path

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent.parent / "playcache" / "assets"
SIZE = 256

INDIGO_LIGHT = QColor("#6366F1")
INDIGO_DARK = QColor("#4338CA")
WHITE = QColor("#FFFFFF")


def render(size: int = SIZE) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    s = float(size)

    # --- Rounded square background with diagonal indigo gradient (the vault) ---
    margin = s * 0.04
    radius = s * 0.22
    rect = QRectF(margin, margin, s - 2 * margin, s - 2 * margin)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, INDIGO_LIGHT)
    grad.setColorAt(1.0, INDIGO_DARK)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(rect, radius, radius)

    # --- White circle (the vault dial / gamepad backdrop) ---
    cx = cy = s / 2.0
    dial_r = s * 0.34
    p.setBrush(QBrush(WHITE))
    p.drawEllipse(QPointF(cx, cy), dial_r, dial_r)

    # --- Gamepad silhouette (indigo) ---
    # Draw the controller body as a rounded "peanut" shape: two circles
    # (left/right grips) connected by a horizontal bar.
    p.setBrush(QBrush(INDIGO_DARK))

    pad_w = dial_r * 1.55      # total width
    pad_h = dial_r * 0.72      # total height
    grip_r = pad_h / 2.0       # grip corner radius
    left = cx - pad_w / 2.0
    top = cy - pad_h / 2.0

    # Two grip circles + connecting bar → peanut shape
    p.drawEllipse(QPointF(left + grip_r, cy), grip_r, grip_r)
    p.drawEllipse(QPointF(left + pad_w - grip_r, cy), grip_r, grip_r)
    p.drawRect(QRectF(left + grip_r, top, pad_w - 2 * grip_r, pad_h))

    # --- D-pad (plus sign) on the left grip ---
    dpad_cx = left + grip_r
    dpad_cy = cy
    dpad_len = grip_r * 0.9     # arm length
    dpad_thick = grip_r * 0.34  # arm thickness
    # Horizontal arm
    p.drawRect(QRectF(dpad_cx - dpad_len / 2, dpad_cy - dpad_thick / 2,
                      dpad_len, dpad_thick))
    # Vertical arm
    p.drawRect(QRectF(dpad_cx - dpad_thick / 2, dpad_cy - dpad_len / 2,
                      dpad_thick, dpad_len))

    # --- Two action buttons (A/B) on the right grip ---
    btn_cx = left + pad_w - grip_r
    btn_offset = grip_r * 0.42   # diagonal spacing
    btn_r = grip_r * 0.18
    # Top-right button
    p.setBrush(QBrush(WHITE))
    p.drawEllipse(QPointF(btn_cx + btn_offset * 0.7, cy - btn_offset), btn_r, btn_r)
    # Bottom-left button
    p.drawEllipse(QPointF(btn_cx - btn_offset * 0.7, cy + btn_offset), btn_r, btn_r)

    # --- Center home button (small dot) ---
    p.setBrush(QBrush(WHITE))
    p.drawEllipse(QPointF(cx, cy), grip_r * 0.14, grip_r * 0.14)

    p.end()
    return pm


def to_png_bytes(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


def main() -> None:
    import sys
    app = QApplication(sys.argv) if not QApplication.instance() else None

    ASSETS.mkdir(parents=True, exist_ok=True)

    big = render(SIZE)

    # Save the 256px PNG for reference / docs / Linux
    png_path = ASSETS / "app.png"
    big.save(str(png_path), "PNG")
    print(f"wrote {png_path}")

    # Build a multi-resolution .ico using Pillow. Passing the 256px image with
    # a ``sizes`` list tells Pillow to embed each requested resolution by
    # downsampling the source (Windows 10/11 support PNG-encoded entries for
    # all sizes including 256).
    from PIL import Image

    sizes = [16, 32, 48, 64, 128, 256]
    img = Image.open(io.BytesIO(to_png_bytes(big)))
    img.load()

    ico_path = ASSETS / "app.ico"
    img.save(str(ico_path), format="ICO",
             sizes=[(sz, sz) for sz in sizes])
    print(f"wrote {ico_path}")

    if app is not None:
        app.quit()


if __name__ == "__main__":
    main()
