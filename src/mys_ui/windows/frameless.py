"""Безрамочное окно с собственной панелью заголовка (брутализм-хром).

Заменяет нативную рамку ОС: своя строка заголовка с брендом, переключателем
темы и кнопками свернуть/развернуть/закрыть. Окно остаётся перетаскиваемым (за
строку заголовка) и масштабируемым (за края) — через системные жесты Qt
(``startSystemMove`` / ``startSystemResize``), что работает и на X11, и на
Wayland, где ручное двигание геометрии недоступно.

Хром — общий для всех экранов: строка заголовка постоянна, ниже — стек контента
(вход ↔ главное), как на дизайн-канве (title bar вне ``sc-if``)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme
from mys_ui.widgets import icons
from mys_ui.widgets.brutal import BrutalButton


class _ChromeTitleBar(QWidget):
    """Строка заголовка: бренд слева, тема + системные кнопки справа.

    Перетаскивание окна — системным жестом, начатым на «движении с зажатой
    кнопкой» (а не на нажатии), чтобы простой клик и двойной клик (развернуть)
    не съедались начавшимся перетаскиванием."""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        # без WA_StyledBackground QSS-фон (barBg) у голого QWidget не рисуется —
        # в светлой теме сквозь панель просвечивает paper-фон окна.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(42)
        self._press = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(22))
        lay.addWidget(logo)

        brand = QLabel("МЫС")
        brand.setObjectName("BrandMark")
        brand.setFont(theme.display_font(25))
        sub = QLabel("DESKTOP")
        sub.setObjectName("BrandSub")
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addStretch()

        self._theme_btn = BrutalButton(
            "СВЕТ" if theme.current_mode() == "dark" else "ТЁМН",
            "default",
            tiny=True,
            ring=True,
        )
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self._theme_btn)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        controls.setContentsMargins(6, 0, 0, 0)
        self._btn_min = BrutalButton("", "default", tiny=True, icon=icons.minimize, ring=True)
        self._btn_min.setFocusPolicy(Qt.NoFocus)
        self._btn_min.clicked.connect(self.minimize_requested)
        self._btn_max = BrutalButton("", "default", tiny=True, icon=icons.maximize, ring=True)
        self._btn_max.setFocusPolicy(Qt.NoFocus)
        self._btn_max.clicked.connect(self.maximize_requested)
        self._btn_close = BrutalButton(
            "", "default", tiny=True, danger=True, icon=icons.close, ring=True
        )
        self._btn_close.setFocusPolicy(Qt.NoFocus)
        self._btn_close.clicked.connect(self.close_requested)
        for b in (self._btn_min, self._btn_max, self._btn_close):
            controls.addWidget(b)
        lay.addLayout(controls)

    def set_maximized(self, maximized: bool) -> None:
        self._btn_max._icon = icons.restore if maximized else icons.maximize
        self._btn_max.update()

    def _toggle_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        new = theme.toggle_theme(app)
        self._theme_btn.setText("СВЕТ" if new == "dark" else "ТЁМН")
        # Кастомно-рисованные представления (пузыри чата) читают токены в paint —
        # принудительно перерисовать после смены палитры.
        win = self.window()
        for view in win.findChildren(QAbstractItemView):
            view.viewport().update()

    # --- перетаскивание окна ---------------------------------------------------

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = True
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press and (e.buttons() & Qt.LeftButton):
            self._press = False
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = False
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.maximize_requested.emit()
        super().mouseDoubleClickEvent(e)


_EDGE = Qt.Edge


class FramelessWindow(QWidget):
    """Безрамочное верхнеуровневое окно: хром-заголовок + стек контента.

    Подклассы кладут экраны в ``self.content`` (``QStackedWidget``). Края окна
    ловят масштабирование через прикладной event-filter и ``startSystemResize``."""

    RESIZE_MARGIN = 6

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowIcon(theme.app_icon())
        self.setMinimumSize(900, 560)
        self._override_active = False
        self._cursor_edges = _EDGE(0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = _ChromeTitleBar(self)
        self.titlebar.minimize_requested.connect(self.showMinimized)
        self.titlebar.maximize_requested.connect(self._toggle_max)
        self.titlebar.close_requested.connect(self.close)
        root.addWidget(self.titlebar)

        self.content = QStackedWidget()
        root.addWidget(self.content, 1)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self.titlebar.set_maximized(self.isMaximized())
        super().changeEvent(e)

    # --- масштабирование за края ------------------------------------------------

    def _edges_at(self, gpos) -> Qt.Edge:
        if self.isMaximized() or self.isFullScreen():
            return _EDGE(0)
        g = self.geometry()  # верхнеуровневое окно → координаты в экране
        m = self.RESIZE_MARGIN
        x, y = gpos.x(), gpos.y()
        if not (g.left() - m <= x <= g.right() + m and g.top() - m <= y <= g.bottom() + m):
            return _EDGE(0)
        edges = _EDGE(0)
        if x <= g.left() + m:
            edges |= _EDGE.LeftEdge
        elif x >= g.right() - m:
            edges |= _EDGE.RightEdge
        if y <= g.top() + m:
            edges |= _EDGE.TopEdge
        elif y >= g.bottom() - m:
            edges |= _EDGE.BottomEdge
        return edges

    @staticmethod
    def _shape_for(edges):
        L, R = _EDGE.LeftEdge, _EDGE.RightEdge
        T, B = _EDGE.TopEdge, _EDGE.BottomEdge
        if (edges & T and edges & L) or (edges & B and edges & R):
            return Qt.SizeFDiagCursor
        if (edges & T and edges & R) or (edges & B and edges & L):
            return Qt.SizeBDiagCursor
        if edges & L or edges & R:
            return Qt.SizeHorCursor
        if edges & T or edges & B:
            return Qt.SizeVerCursor
        return None

    def _apply_cursor(self, edges) -> None:
        if edges == self._cursor_edges:
            return
        self._cursor_edges = edges
        shape = self._shape_for(edges)
        if shape is None:
            if self._override_active:
                QApplication.restoreOverrideCursor()
                self._override_active = False
        elif self._override_active:
            QApplication.changeOverrideCursor(QCursor(shape))
        else:
            QApplication.setOverrideCursor(QCursor(shape))
            self._override_active = True

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edges = self._edges_at(QCursor.pos())
            if edges:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    return True
        elif t == QEvent.MouseMove:
            if not (QApplication.mouseButtons() & Qt.LeftButton):
                self._apply_cursor(self._edges_at(QCursor.pos()))
        return super().eventFilter(obj, event)


class _DialogTitleBar(QWidget):
    """Упрощённая строка заголовка для диалогов: название + закрыть, перетаскивание."""

    close_requested = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("DialogBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(34)
        self._press = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 6, 0)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setObjectName("DialogBarTitle")
        lay.addWidget(lbl)
        lay.addStretch()
        btn = BrutalButton("", "default", tiny=True, danger=True, icon=icons.close, ring=True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(self.close_requested)
        lay.addWidget(btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = True
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press and (e.buttons() & Qt.LeftButton):
            self._press = False
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = False
        super().mouseReleaseEvent(e)


class FramelessDialog(QDialog):
    """Безрамочный диалог с тем же стилем, что и главное окно, но проще.

    Тонкая ink-строка заголовка (название + закрыть) и 2px ink-рамка вокруг —
    чтобы держать брутализм-стиль. Подклассы кладут содержимое в ``self.body``
    (его layout — ``self.body_layout``). Перетаскивание за строку заголовка."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("FramelessDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)  # 2px ink-фон = рамка
        outer.setSpacing(0)

        bar = _DialogTitleBar(title)
        bar.close_requested.connect(self.reject)
        outer.addWidget(bar)

        self.body = QWidget()
        self.body.setObjectName("DialogBody")
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self.body)

        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(28, 24, 28, 24)
        self.body_layout.setSpacing(8)
