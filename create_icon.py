"""
Generate images/icon.ico for the Windows exe.

Run once before building:
    uv run python create_icon.py

Requires no extra dependencies — uses only PySide6 (already a project dep).
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

SIZES = [16, 32, 48, 256]
BG_COLOUR = "#1a1a1a"
ACCENT_COLOUR = "#e8a000"
TEXT_COLOUR = "#ffffff"


def make_pixmap(size: int) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(QColor(BG_COLOUR))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Amber circle
    p.setBrush(QColor(ACCENT_COLOUR))
    p.setPen(Qt.PenStyle.NoPen)
    margin = max(1, size // 10)
    p.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)

    # "RE" text
    p.setPen(QColor(TEXT_COLOUR))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(6, int(size * 0.42)))
    p.setFont(font)
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "RE")
    p.end()
    return px


def main() -> None:
    app = QApplication(sys.argv)

    os.makedirs("images", exist_ok=True)
    path = os.path.join("images", "icon.ico")

    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(make_pixmap(size))

    # Save as ICO via the largest pixmap — Qt writes multi-size ICO on Windows;
    # on Mac/Linux it writes a PNG inside the .ico container (fine for PyInstaller).
    px = make_pixmap(256)
    px.save(path, "ICO")

    print(f"Icon written to {path}")


if __name__ == "__main__":
    main()
