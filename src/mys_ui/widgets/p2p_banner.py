"""Оверлей P2P-беседы, когда собеседник офлайн: плашка с реконнектом и таймером.

Две подсостояния одного виджета (без отдельных страниц стека — переключаются
показом/скрытием блоков):
  - ``idle`` — «СОБЕСЕДНИК ОФЛАЙН» + большая красная кнопка «ВЫЙТИ НА СВЯЗЬ»;
  - ``connecting`` — обратный отсчёт (до 5 минут) вместо кнопки, пока ждём, что
    собеседник тоже подключится (см. ``MainWindow``: тот же виджет используется
    и при первом подключении к новому каналу, и при реконнекте к старому).

Ссылка «прочитать переписку» видна в обоих подсостояниях: снимает оверлей и
даёт доступ к истории, не прерывая попытку подключения, если она идёт в фоне.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from mys_ui import theme
from mys_ui.widgets import icons
from mys_ui.widgets.brutal import BrutalButton

# Фиксированная высота подзаголовка (см. _subtitle ниже) — с запасом под 6 строк
# текста на его 17px из QSS (QLabel#P2PBannerSubtitle). Не считаем через
# QFontMetrics: на момент __init__ виджет ещё не оформлен стилем приложения,
# метрики шрифта по умолчанию не совпали бы с реальными 17px. Небольшой излишек
# высоты не страшен — контент центрирован по вертикали блоком.
_SUBTITLE_HEIGHT = 130


class P2POfflineBanner(QWidget):
    reconnect_requested = Signal()
    read_history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("P2POfflineBanner")

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)
        root.setSpacing(18)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setPixmap(icons.pixmap(icons.warning, 40, theme.tokens()["warn"]))
        root.addWidget(self._icon)

        self._title = QLabel("")
        self._title.setObjectName("P2PBannerTitle")
        self._title.setAlignment(Qt.AlignCenter)
        root.addWidget(self._title)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("P2PBannerSubtitle")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setMaximumWidth(400)
        # Высота словообёрнутого QLabel в QVBoxLayout считается через
        # heightForWidth, а maximumWidth сужает ширину уже ПОСЛЕ первого прохода
        # раскладки — рассинхрон даёт наложение строк (особенно на offscreen QPA,
        # где propagateSizeHints недоступен). Резервируем фиксированную высоту
        # один раз — обе подсостояния укладываются, наложений не будет.
        self._subtitle.setFixedHeight(_SUBTITLE_HEIGHT)
        root.addWidget(self._subtitle, 0, Qt.AlignHCenter)

        self._note = QLabel("")
        self._note.setObjectName("P2PBannerNote")
        self._note.setAlignment(Qt.AlignCenter)
        self._note.hide()
        root.addWidget(self._note)

        self._countdown = QLabel("")
        self._countdown.setObjectName("P2PBannerCountdown")
        self._countdown.setAlignment(Qt.AlignCenter)
        self._countdown.hide()
        root.addWidget(self._countdown)

        self._btn_reconnect = BrutalButton("ВЫЙТИ НА СВЯЗЬ", "danger")
        self._btn_reconnect.clicked.connect(self.reconnect_requested)
        root.addWidget(self._btn_reconnect, 0, Qt.AlignHCenter)

        self._link_history = QLabel('<a href="#">прочитать переписку</a>')
        self._link_history.setObjectName("P2PBannerLink")
        self._link_history.setAlignment(Qt.AlignCenter)
        self._link_history.setTextFormat(Qt.RichText)
        self._link_history.setOpenExternalLinks(False)
        self._link_history.setCursor(Qt.PointingHandCursor)
        self._link_history.linkActivated.connect(
            lambda _href: self.read_history_requested.emit()
        )
        root.addWidget(self._link_history)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._remaining = 0

        self.set_idle()

    # -- подсостояния -------------------------------------------------------

    def set_idle(self, *, note: str = "") -> None:
        """Показать кнопку «Выйти на связь» (таймер, если шёл, — остановить)."""
        self._timer.stop()
        self._title.setText("СОБЕСЕДНИК ОФЛАЙН")
        self._subtitle.setText(
            "Нажмите кнопку. Если в ближайшие 5 минут собеседник сделает то же "
            "самое — разговор возобновится."
        )
        if note:
            self._note.setText(note)
            self._note.show()
        else:
            self._note.hide()
        self._countdown.hide()
        self._btn_reconnect.show()
        self._subtitle.show()

    def start_countdown(
        self, seconds: int, *, title: str = "ОЖИДАЕМ СОБЕСЕДНИКА…",
    ) -> None:
        """Показать обратный отсчёт вместо кнопки (идёт попытка подключения)."""
        self._title.setText(title)
        self._subtitle.setText(
            "Держим канал открытым — собеседник может подключиться "
            "в любой момент до конца отсчёта."
        )
        self._note.hide()
        self._btn_reconnect.hide()
        self._remaining = max(0, int(seconds))
        self._countdown.show()
        self._render_countdown()
        self._timer.start()

    def stop(self) -> None:
        """Остановить таймер без смены текста (виджет сейчас скрывается/сменяется)."""
        self._timer.stop()

    # -- обратный отсчёт ------------------------------------------------------

    def _tick(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
        self._render_countdown()
        if self._remaining <= 0:
            self._timer.stop()

    def _render_countdown(self) -> None:
        m, s = divmod(max(0, self._remaining), 60)
        self._countdown.setText(f"{m:01d}:{s:02d}")
