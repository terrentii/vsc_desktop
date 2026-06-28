"""Блок кода: бар «//// code» + кнопка «Копировать» + моноширинный pre.

Структура повторяет .code-block из vsc_web (без подсветки синтаксиса).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme


class CodeBlock(QWidget):
    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self._code = code
        t = theme.tokens()
        self.setObjectName("CodeBlock")
        self.setStyleSheet(
            f"#CodeBlock {{ border: 1px solid {t['border2']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("CodeBar")
        bar.setStyleSheet(f"#CodeBar {{ background: {t['surface']}; }}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 5, 10, 5)
        label = QLabel("//// code")
        label.setStyleSheet(
            f"color: {t['text3']}; font-family: monospace;"
            " font-size: 10px; letter-spacing: 2px;"
        )
        self.copy_btn = QPushButton("Копировать")
        self.copy_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['text3']};"
            f" border: 1px solid {t['border2']}; padding: 2px 10px;"
            " font-family: monospace; font-size: 10px; }"
        )
        self.copy_btn.clicked.connect(self._copy)
        bl.addWidget(label)
        bl.addStretch()
        bl.addWidget(self.copy_btn)
        root.addWidget(bar)

        self.pre = QPlainTextEdit()
        self.pre.setReadOnly(True)
        self.pre.setPlainText(code)
        self.pre.setFrameShape(QPlainTextEdit.NoFrame)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)
        mono.setPixelSize(12)
        self.pre.setFont(mono)
        self.pre.setStyleSheet(
            f"QPlainTextEdit {{ background: {t['surface']}; color: {t['text']};"
            " padding: 8px 12px; }"
        )
        # высота под контент (без внутреннего скролла на коротком коде):
        # считаем по реальной межстрочной высоте моно-шрифта + вертикальный padding.
        from PySide6.QtGui import QFontMetrics

        line_h = QFontMetrics(mono).lineSpacing()
        lines = code.count("\n") + 1
        # запас: padding QSS (8+8) + document margin (2*4) + небольшой буфер
        chrome = 16 + 2 * int(self.pre.document().documentMargin()) + 6
        self.pre.setFixedHeight(min(max(lines, 1), 20) * line_h + chrome)
        if lines <= 20:  # помещается целиком — без внутреннего скролла
            self.pre.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.pre)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._code)
