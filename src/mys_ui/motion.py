"""Анимации интерфейса: короткие и тихие — проявление экранов, плавная прокрутка.

Эффект прозрачности снимается по окончании: постоянный QGraphicsEffect на большом
дереве виджетов замедляет отрисовку и мешает вложенным эффектам.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

FADE_MS = 200
SCROLL_MS = 260


def fade_in(widget: QWidget, ms: int = FADE_MS) -> None:
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget._mys_fade = anim  # держим ссылку до конца анимации
    anim.start()


def smooth_scroll(scrollbar, to: int, ms: int = SCROLL_MS) -> None:
    anim = QPropertyAnimation(scrollbar, b"value", scrollbar)
    anim.setDuration(ms)
    anim.setStartValue(scrollbar.value())
    anim.setEndValue(to)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    scrollbar._mys_scroll = anim
    anim.start()
