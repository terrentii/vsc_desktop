"""ГОСТ-иконки: тонкоштриховые векторные значки в стиле чертёжного шрифта.

Рисуются через ``QPainter`` (как и системные кнопки хром-окна), без растровых
ассетов — единый монохромный язык: равномерный штрих, прямые засечки (FlatCap +
MiterJoin), геометрия по сетке. Это технический рисунок в духе ГОСТ 2.304: ничего
лишнего, один цвет (берётся из токена темы в момент отрисовки).

Каждая функция — ``draw(painter, rect, color)`` и пригодна и как ``icon=`` для
``BrutalButton`` (рисует поверх лица кнопки), и как источник для ``pixmap`` (для
``QLabel``-значков). Прямолинейные значки крепкие без сглаживания (брутализм-кант);
кривые (скрепка) локально включают антиалиасинг.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

_STROKE = 1.6  # равномерный чертёжный штрих


def _pen(color, width: float = _STROKE, *, round_cap: bool = False) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap if round_cap else Qt.FlatCap)
    pen.setJoinStyle(Qt.MiterJoin)
    return pen


def _inset(r: QRect, frac: float = 0.25) -> QRect:
    pad = max(3, int(min(r.width(), r.height()) * frac))
    return r.adjusted(pad, pad, -pad, -pad)


# --- системные значки окна --------------------------------------------------

def minimize(p: QPainter, r: QRect, color) -> None:
    """Горизонтальная полоса — свернуть."""
    p.setPen(_pen(color))
    cx = r.center().x()
    cy = r.center().y()
    hw = max(1, r.width() // 4)
    p.drawLine(cx - hw, cy, cx + hw, cy)


def maximize(p: QPainter, r: QRect, color) -> None:
    """Квадратный контур — развернуть."""
    p.setPen(_pen(color))
    p.drawRect(_inset(r))


def restore(p: QPainter, r: QRect, color) -> None:
    """Равносторонний треугольник вниз — восстановить из полного экрана."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(_pen(color))
    b = _inset(r)
    # _inset даёт вырожденный rect на маленьких кнопках — берём центр из r напрямую
    cx = r.left() + r.width() / 2.0
    cy = r.top() + r.height() / 2.0
    s = float(r.width()) * 0.7    # сторона — 70% ширины rect
    h = s * (3 ** 0.5) / 2        # высота равностороннего треугольника
    # ▽: основание сверху → центроид на h/3 от верха; ставим его в cy
    top_y = cy - h / 2
    bot_y = cy + h / 2
    p.drawPolygon(QPolygonF([
        QPointF(cx - s / 2, top_y),
        QPointF(cx + s / 2, top_y),
        QPointF(cx,          bot_y),
    ]))
    p.restore()


def close(p: QPainter, r: QRect, color) -> None:
    """Косой крест — закрыть."""
    p.setPen(_pen(color, round_cap=True))
    b = _inset(r)
    p.drawLine(b.topLeft(), b.bottomRight())
    p.drawLine(b.topRight(), b.bottomLeft())


# --- контентные значки ------------------------------------------------------

def attach(p: QPainter, r: QRect, color) -> None:
    """Скрепка — прикрепить файл."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(_pen(color, _STROKE, round_cap=True))

    cx = r.center().x()
    rw, rh = r.width(), r.height()

    clip_w = rw * 0.50              # ширина скрепки
    left = cx - clip_w / 2
    right = cx + clip_w / 2
    top = r.top() + rh * 0.10
    bottom = r.top() + rh * 0.90

    r_bot = clip_w / 2             # радиус нижней дуги
    inner_left = left + clip_w * 0.35
    r_top = (right - inner_left) / 2   # радиус верхнего крючка

    bot_cy = bottom - r_bot         # центр нижней дуги по Y
    top_cy = top + r_top            # центр верхнего крючка по Y

    path = QPainterPath()
    # левый (внешний) ус — вниз
    path.moveTo(left, top)
    path.lineTo(left, bot_cy)
    # нижняя U-дуга: левая → правая (по часовой)
    path.arcTo(QRectF(left, bottom - clip_w, clip_w, clip_w), 180, -180)
    # правый ус — вверх к крючку
    path.lineTo(right, top_cy)
    # верхний крючок: правая → inner_left (против часовой, через верх)
    path.arcTo(QRectF(inner_left, top, right - inner_left, r_top * 2), 0, 180)
    # внутренний (короткий) ус — вниз до середины
    path.lineTo(inner_left, top + (bottom - top) * 0.55)

    p.drawPath(path)
    p.restore()


def warning(p: QPainter, r: QRect, color) -> None:
    """Треугольник с восклицательным знаком — предупреждение."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(_pen(color))
    b = _inset(r, 0.14)
    apex = QPointF(b.center().x(), float(b.top()))
    p.drawPolygon(QPolygonF([apex, QPointF(b.right(), b.bottom()), QPointF(b.left(), b.bottom())]))
    cx = b.center().x()
    p.drawLine(QPointF(cx, b.top() + b.height() * 0.36), QPointF(cx, b.top() + b.height() * 0.62))
    dot = b.top() + b.height() * 0.78
    p.fillRect(QRectF(cx - 1, dot - 1, 2, 2), QColor(color))
    p.restore()


# --- рендер в QPixmap (для QLabel-значков) -----------------------------------

def pixmap(draw, size: int, color, *, ratio: float = 2.0) -> QPixmap:
    """Отрисовать значок ``draw`` в прозрачный ``QPixmap`` ``size``×``size``.

    Рендерит в ``ratio``-кратном разрешении (HiDPI-чёткость) и помечает DPR, так
    что метка показывает значок резко на любом экране."""
    px = max(1, int(size * ratio))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    draw(p, QRect(0, 0, px, px), color)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm
