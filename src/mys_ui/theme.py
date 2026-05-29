"""Минимальная тёмная тема (без излишеств)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def apply_dark_theme(app) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    bg = QColor(37, 37, 38)
    base = QColor(30, 30, 30)
    text = QColor(220, 220, 220)
    accent = QColor(58, 110, 165)
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, bg)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, Qt.white)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    app.setPalette(p)
