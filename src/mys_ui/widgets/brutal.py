"""Брутализм-виджеты дизайн-системы МЫС: кнопка, поле ввода, чекбокс.

Сигнатура DS — жёсткие смещённые тени, которые «вдавливаются» при нажатии
(сдвиг 2px → тень 2px → 0, «клац»), квадратные углы, ink-границы и единый
кобальтовый акцент. QSS не умеет ни ``box-shadow``, ни анимацию состояний, поэтому
кнопка и чекбокс рисуются вручную; поле ввода зажигает кобальтовую тень на фокусе
реальным ``QGraphicsDropShadowEffect`` (нулевой радиус = чёткое смещение).

Spec: preview/components-buttons.html, components-inputs.html, spacing-shadows.html.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsDropShadowEffect,
    QLineEdit,
    QPushButton,
)

from mys_ui import theme

# Варианты: цвета лица/текста берутся из токенов темы в момент отрисовки.
# primary — кобальт; ink — чернильная заливка; danger — warn; default — surface;
# minimal — без тени, hairline-граница, ховер = инверсия (для модалок/тулбаров).
_BRUTAL = ("primary", "default", "ink", "danger")


class BrutalButton(QPushButton):
    def __init__(
        self,
        text: str = "",
        variant: str = "default",
        *,
        small: bool = False,
        tiny: bool = False,
        danger: bool = False,
        shadow: str = "line",
        icon=None,
        ring: bool = False,
        parent=None,
    ):
        super().__init__(text, parent)
        self._variant = variant
        self._small = small
        self._tiny = tiny
        self._danger = danger
        self._shadow_tok = shadow  # ключ токена цвета тени (line | accent | …)
        self._icon = icon          # callable(QPainter, QRect, QColor) или None
        # ring: в светлой теме хром-кнопки лежат на тёмной строке заголовка, и их
        # тёмная рамка сливается с фоном — добавляем внешнее белое кольцо, чтобы
        # читались и «светлое лицо», и тёмная рамка после него.
        self._ring = ring
        self._hover = False
        self._pressed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFont(self._mk_font())
        self.toggled.connect(self.update)  # перерисовать активную вкладку

    def _mk_font(self) -> QFont:
        # единый язык: mono-капс для всех кнопок (как у «+ Новый канал»)
        f = QFont()
        f.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
        f.setBold(True)
        if self._tiny:
            f.setPixelSize(4)
        elif self._small:
            f.setPixelSize(12)
        else:
            f.setPixelSize(14)
        f.setCapitalization(QFont.AllUppercase)
        f.setLetterSpacing(QFont.PercentageSpacing, 109)
        return f

    # --- геометрия -------------------------------------------------------------

    def _shadow(self) -> int:
        if self._tiny:
            return 1
        return 3 if self._small else 4

    def _pad(self) -> tuple[int, int]:
        if self._tiny:
            return (1, 3)
        return (6, 14) if self._small else (8, 20)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        pv, ph = self._pad()
        extra = 0 if self._tiny else 4  # дополнительный «воздух» — не для tiny
        h = fm.height() + 2 * pv + extra
        s = self._shadow()
        bump = 1 if self._ring else 0
        if self._icon is not None and not self.text():
            return QSize(h + s + bump, h + s + bump)
        w = fm.horizontalAdvance(self.text()) + 2 * ph + extra
        return QSize(w + s + bump, h + s + bump)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # --- состояния -------------------------------------------------------------

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = self._pressed = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(e)

    # --- цвета -----------------------------------------------------------------

    def _colors(self, t):
        """Возвращает (лицо, текст, граница, цвет тени)."""
        # активная вкладка (checkable) — как primary
        # (рамка ink: кобальт не сливается с тёмным фоном/белой тенью)
        if self.isCheckable() and self.isChecked():
            return t["accent"], "#ffffff", t["ink"], t["line"]
        v = self._variant
        if v == "primary":
            return t["accent"], "#ffffff", t["ink"], t["line"]
        if v == "ink":
            return t["line"], t["bg"], t["line"], t.get(self._shadow_tok, t["line"])
        if v == "danger":
            return t["warn"], "#ffffff", t["line"], t["line"]
        # вторичная «опасная» (Блокировка/Выйти): surface-лицо, warn-акценты
        if self._danger:
            return t["surface"], t["warn"], t["warn"], t["warn"]
        # default / minimal — surface-лицо с ink-границей и тенью
        return t["surface"], t["text"], t["line"], t.get(self._shadow_tok, t["line"])

    # --- отрисовка -------------------------------------------------------------

    def paintEvent(self, e):
        t = theme.tokens()
        face_bg, fg, border, shadow_col = self._colors(t)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()

        s = self._shadow()
        if self._pressed:
            fd = s
        elif self._hover:
            fd = s // 2
        else:
            fd = 0
        fw, fh = w - s, h - s

        ring = self._ring and theme.current_mode() == "light"
        if ring:
            # Тёмная блок-тень слилась бы с тёмной строкой заголовка → даём
            # контрастную белую в том же нижне-правом углу, что и у остальных
            # кнопок (лицо «приподнято» вверх-влево). При нажатии лицо наезжает.
            shadow_col = "#ffffff"
        if fd < s:
            p.fillRect(QRect(s, s, fw, fh), QColor(shadow_col))
        face = QRect(fd, fd, fw, fh)
        if ring:
            # белое кольцо ~2px вылезает из-под жирной (3px) тёмной рамки, чтобы
            # рамка «выпирала» на тёмной строке заголовка и не сливалась с фоном.
            peek, bw = 1, 1
            p.fillRect(face, QColor("#ffffff"))
            p.fillRect(face.adjusted(peek, peek, -peek, -peek), QColor(border))
            d = peek + bw
            inner = face.adjusted(d, d, -d, -d)
        else:
            p.fillRect(face, QColor(border))
            inner = face.adjusted(2, 2, -2, -2)
        p.fillRect(inner, QColor(face_bg))
        if self._icon is not None:
            self._icon(p, inner, QColor(fg))
        else:
            p.setPen(QColor(fg))
            p.drawText(face, Qt.AlignCenter, self.text())


class BrutalLineEdit(QLineEdit):
    """Поле ввода с кобальтовой смещённой тенью на фокусе (DS focus-ring)."""

    def focusInEvent(self, e):
        eff = QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(0)
        eff.setOffset(4, 4)
        eff.setColor(QColor(theme.tokens()["accent"]))
        self.setGraphicsEffect(eff)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.setGraphicsEffect(None)
        super().focusOutEvent(e)


class BrutalCheckBox(QCheckBox):
    """Чекбокс DS: 18px, 1.5px ink-граница; отмечен — ink-заливка + кобальт-квадрат."""

    _BOX = 18

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        f = QFont()
        f.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
        f.setPixelSize(16)
        self.setFont(f)

    def paintEvent(self, e):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        b = self._BOX
        top = (self.height() - b) // 2
        box = QRect(0, top, b, b)
        p.fillRect(box, QColor(t["field"]))
        if self.isChecked():
            inner = box.adjusted(2, 2, -2, -2)
            p.fillRect(inner, QColor(t["line"]))
            mark = QRect(0, 0, 8, 8)
            mark.moveCenter(box.center())
            p.fillRect(mark, QColor(t["accent"]))
        p.setPen(QPen(QColor(t["line"]), 2))
        p.drawRect(box.adjusted(1, 1, -1, -1))
        # подпись
        p.setPen(QColor(t["text2"]))
        text_rect = QRect(b + 10, 0, self.width() - b - 10, self.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        w = self._BOX + 10 + fm.horizontalAdvance(self.text()) + 2
        return QSize(w, max(self._BOX + 2, fm.height()))
