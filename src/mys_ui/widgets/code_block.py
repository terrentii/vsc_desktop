"""Блок кода: бар «//// code» + кнопка «Копировать» + моноширинный pre.

Структура повторяет .code-block из vsc_web (без подсветки синтаксиса).
"""

from PySide6.QtCore import Qt, QTimer
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
        # Как .code-block в vsc_web: рамка, бар «//// CODE» + «Копировать», моно 16px.
        self.setObjectName("CodeBlock")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#CodeBlock {{ border: 1px solid {t['border2']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("CodeBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"#CodeBar {{ background: {t['surface3']};"
            f" border-bottom: 1px solid {t['border2']}; }}"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 5, 10, 5)
        label = QLabel("////  CODE")
        label.setFont(theme.mono_font(14))
        label.setStyleSheet(f"color: {t['text2']};")
        self.copy_btn = QPushButton("Копировать")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setFont(theme.mono_font(13, spacing=0.08))
        self.copy_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['text2']};"
            f" border: 1px solid {t['text3']}; padding: 2px 10px; }}"
            f"QPushButton:hover {{ color: {t['text']}; border-color: {t['text']}; }}"
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
        self.pre.setLineWrapMode(QPlainTextEdit.NoWrap)  # как overflow-x: auto
        mono = theme.mono_font(16)
        self.pre.setFont(mono)
        self.pre.setStyleSheet(
            f"QPlainTextEdit {{ background: {t['surface2']}; color: {t['text']};"
            " padding: 8px 12px; }"
        )
        # высота под контент (без внутреннего скролла на коротком коде):
        # реальная межстрочная высота моно-шрифта + padding + место под гориз. скролл.
        from PySide6.QtGui import QFontMetrics

        line_h = QFontMetrics(mono).lineSpacing()
        lines = code.count("\n") + 1
        chrome = 16 + 2 * int(self.pre.document().documentMargin()) + 6
        hbar = self.pre.horizontalScrollBar().sizeHint().height()
        self.pre.setFixedHeight(min(max(lines, 1), 20) * line_h + chrome + hbar)
        if lines <= 20:  # помещается целиком — без внутреннего скролла
            self.pre.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.pre)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._code)
        self.copy_btn.setText("Скопировано!")
        QTimer.singleShot(2000, lambda: self.copy_btn.setText("Копировать"))
