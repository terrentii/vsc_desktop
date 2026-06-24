"""Главное окно: заголовок, панель инструментов, список/чат, статус-бар."""

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mys_centralized.errors import CentralizedError

from mys_ui import theme
from mys_ui.controller import CENTRALIZED, DECENTRALIZED
from mys_ui.dialogs.central import CentralLoginDialog
from mys_ui.dialogs.phrase import PhraseDialog
from mys_ui.dialogs.settings import SettingsDialog
from mys_ui.widgets.chat_view import ChatView
from mys_ui.widgets.conversation_list import ConversationList
from mys_ui.widgets.message_input import MessageInput
from mys_ui.widgets.top_bar import TopBar


class _CentralBridge(QObject):
    """Мост из потока централизованного сервиса в UI-поток через Qt-сигналы.

    Колбэки сервиса (фоновый поток) лишь вызывают ``emit``; Qt доставляет их в
    UI-поток (queued-соединение), где слоты безопасно трогают виджеты."""

    message = Signal(int, int)
    state = Signal(str)
    error = Signal(str)
    resumed = Signal(bool)


class MainWindow(QWidget):
    locked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._current: int | None = None
        self._central_error: str | None = None
        self._central_state: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())

        self.top = TopBar()
        root.addWidget(self.top)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(0)
        self.conversations = ConversationList()
        self.conversations.setMinimumWidth(240)
        split.addWidget(self.conversations)
        split.addWidget(self._build_chat_pane())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([294, 700])
        root.addWidget(split, 1)

        root.addWidget(self._build_status_bar())

        self.top.mode_changed.connect(self._on_mode)
        self.top.lock_requested.connect(self.locked)
        self.top.settings_requested.connect(self._open_settings)
        self.top.login_requested.connect(self._central_login)
        self.conversations.conversation_selected.connect(self._on_select)
        self.conversations.new_conversation_requested.connect(self._on_new)
        self.input.message_submitted.connect(self._on_send)

        # Мост real-time централизованного режима.
        self._bridge = _CentralBridge()
        self._bridge.message.connect(self._on_central_message)
        self._bridge.state.connect(self._on_central_state)
        self._bridge.error.connect(self._on_central_error)
        self._bridge.resumed.connect(self._on_resumed)
        self._c.add_central_observer(
            on_message=lambda cid, lid: self._bridge.message.emit(cid, lid),
            on_state_change=lambda st: self._bridge.state.emit(st),
            on_error=lambda exc: self._bridge.error.emit(str(exc)),
        )

        self._sync_mode_ui()
        self.refresh_conversations()
        self._try_auto_resume()

    # --- сборка UI -------------------------------------------------------------

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(42)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(12)
        brand = QLabel("МЫС")
        brand.setObjectName("BrandMark")
        sub = QLabel("DESKTOP")
        sub.setObjectName("BrandSub")
        self._theme_btn = QPushButton(
            "LIGHT" if theme.current_mode() == "dark" else "DARK"
        )
        self._theme_btn.setObjectName("ThemeToggle")
        self._theme_btn.setCursor(Qt.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addStretch()
        lay.addWidget(self._theme_btn)
        return bar

    def _build_chat_pane(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("ChatPane")
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # шапка чата
        self._chat_header = QWidget()
        self._chat_header.setObjectName("ChatHeader")
        hh = QHBoxLayout(self._chat_header)
        hh.setContentsMargins(18, 12, 18, 12)
        col = QVBoxLayout()
        col.setSpacing(3)
        self._chat_name = QLabel("")
        self._chat_name.setObjectName("ChatName")
        self._chat_sub = QLabel("")
        self._chat_sub.setObjectName("ChatSub")
        col.addWidget(self._chat_name)
        col.addWidget(self._chat_sub)
        hh.addLayout(col, 1)
        self._chat_badge = QLabel("")
        self._chat_badge.setObjectName("ChatBadge")
        hh.addWidget(self._chat_badge, 0, Qt.AlignTop)
        v.addWidget(self._chat_header)

        # переключатель «пусто / чат»
        self._chat_stack = QStackedWidget()
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.setAlignment(Qt.AlignCenter)
        self._empty_label = QLabel("ВЫБЕРИТЕ ДИАЛОГ\nИЛИ НАЧНИТЕ НОВЫЙ")
        self._empty_label.setObjectName("EmptyState")
        self._empty_label.setAlignment(Qt.AlignCenter)
        ev.addWidget(self._empty_label)
        self._chat_stack.addWidget(empty)

        chat_box = QWidget()
        cv = QVBoxLayout(chat_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.chat = ChatView()
        self.input = MessageInput()
        cv.addWidget(self.chat, 1)
        cv.addWidget(self.input)
        self._chat_stack.addWidget(chat_box)
        v.addWidget(self._chat_stack, 1)

        self._update_chat_header()
        return pane

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(26)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        dot = QLabel()
        dot.setObjectName("StatusDot")
        dot.setFixedSize(8, 8)
        self._status_text = QLabel("ГОТОВО")
        self._status_text.setObjectName("StatusText")
        self._status_mono = QLabel("")
        self._status_mono.setObjectName("StatusMono")
        lay.addWidget(dot)
        lay.addSpacing(8)
        lay.addWidget(self._status_text)
        lay.addStretch()
        lay.addWidget(self._status_mono)
        return bar

    def _set_status(self, text: str) -> None:
        self._status_text.setText(text.upper())

    def _toggle_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        new = theme.toggle_theme(app)
        self._theme_btn.setText("LIGHT" if new == "dark" else "DARK")
        self.chat.viewport().update()  # пузыри перерисовать в новых цветах

    # --- режимы ----------------------------------------------------------------

    def _sync_mode_ui(self) -> None:
        """Отразить текущий режим/сессию в панелях (чипы, заголовки списка)."""
        mode = self._c.mode
        self.conversations.set_mode(mode)
        account = None
        if mode == CENTRALIZED:
            sess = self._c.central_session()
            account = getattr(sess, "username", None) if sess else None
        self.top.update_status(mode, account=account)
        self._status_mono.setText(
            "P2P · E2E" if mode == DECENTRALIZED else "ЦЕНТР · soufos.ru"
        )

    def _on_mode(self, mode: str) -> None:
        self._c.set_mode(mode)
        self._current = None
        self.chat.clear()
        self._update_chat_header()
        if (
            mode == CENTRALIZED
            and self._c.central_available()
            and self._c.central_session() is None
        ):
            self._central_login()
        self._sync_mode_ui()
        self.refresh_conversations()
        self._set_status(f"Режим: {'Центр' if mode == CENTRALIZED else 'P2P'}")

    def _central_login(self) -> None:
        dialog = CentralLoginDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        url, username, password = dialog.values()
        if not self._perform_central_login(url, username, password, dialog.is_register()):
            QMessageBox.warning(self, "Вход не выполнен", self._central_error or "Ошибка")

    def _perform_central_login(self, url, username, password, register: bool) -> bool:
        """Выполнить вход (без модальных окон) — возвращает успех. Тестируемо."""
        self._central_error = None
        try:
            self._c.central_login(url, username, password, register=register)
        except CentralizedError as exc:
            self._central_error = str(exc)
            return False
        self._sync_mode_ui()
        self.refresh_conversations()
        self._set_status("Вход выполнен")
        return True

    def _try_auto_resume(self) -> None:
        """При старте восстановить сохранённую централизованную сессию в фоне.

        Без повторного входа: если в vault лежит сессия, поднимаем сервис, синк и
        live-WS в фоновом потоке (resume() блокирует до конца первичного синка —
        не держим UI-поток). Нет сессии/фабрики или сессия уже активна → выходим."""
        if not self._c.central_available() or self._c.central_session() is not None:
            return
        if not self._c.central_has_saved_session():
            return
        threading.Thread(
            target=self._resume_worker, name="mys-central-resume", daemon=True
        ).start()

    def _resume_worker(self) -> None:
        """Тело фонового потока: resume() и сигнал результата в UI-поток."""
        ok = False
        try:
            ok = self._c.central_resume() is not None
        except CentralizedError as exc:
            self._central_error = str(exc)
        self._bridge.resumed.emit(ok)

    def _on_resumed(self, ok: bool) -> None:
        # Сессия восстановлена в фоне; если уже в режиме «Центр» — показать комнаты.
        if ok and self._c.mode == CENTRALIZED:
            self._sync_mode_ui()
            self.refresh_conversations()

    # --- выбор/отправка/создание ----------------------------------------------

    def refresh_conversations(self) -> None:
        self.conversations.populate(self._c.list_conversations())

    def add_conversation(self, title: str, *, room_phrase: str | None = None) -> None:
        self._c.create_conversation(title, room_phrase=room_phrase)
        self.refresh_conversations()

    def _on_select(self, conversation_id: int) -> None:
        self._current = conversation_id
        self.chat.show_messages(self._c.list_messages(conversation_id))
        self._update_chat_header()

    def _on_new(self) -> None:
        if self._c.mode == DECENTRALIZED:
            dialog = PhraseDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.phrase():
                self.add_conversation(dialog.phrase(), room_phrase=dialog.phrase())
                self._set_status("Канал открыт")
        else:
            title, ok = QInputDialog.getText(self, "Новый диалог", "Название:")
            if ok and title:
                self.add_conversation(title)
                self._set_status("Комната создана")

    def _on_send(self, text: str) -> None:
        if self._current is None:
            return
        self._c.send_message(self._current, text)
        self.chat.show_messages(self._c.list_messages(self._current))
        self._set_status("Сообщение отправлено")

    def _update_chat_header(self) -> None:
        """Показать шапку выбранного диалога либо пустое состояние."""
        if self._current is None:
            self._chat_header.hide()
            self._chat_stack.setCurrentIndex(0)
            return
        title, room = "", ""
        for row in self._c.list_conversations():
            if row["id"] == self._current:
                title = row.get("title") or f"Диалог {row['id']}"
                rid = row.get("room_id")
                if isinstance(rid, (bytes, bytearray)):
                    rid = rid.decode("utf-8", "replace")
                room = str(rid) if rid else ""
                break
        self._chat_name.setText(title)
        if self._c.mode == DECENTRALIZED:
            self._chat_sub.setText("P2P · ШИФРОВАННЫЙ КАНАЛ")
            self._chat_badge.setText("E2E · RATCHET")
        else:
            self._chat_sub.setText(f"ROOM {room}" if room else "ЦЕНТР")
            self._chat_badge.setText("soufos.ru")
        self._chat_header.show()
        self._chat_stack.setCurrentIndex(1)

    # --- real-time централизованного режима ------------------------------------

    def _on_central_message(self, conversation_id: int, _local_id: int) -> None:
        self.refresh_conversations()  # могла появиться новая комната
        if conversation_id == self._current:
            self.chat.show_messages(self._c.list_messages(conversation_id))

    def _on_central_state(self, state: str) -> None:
        self._central_state = state
        self._set_status(state)

    def _on_central_error(self, message: str) -> None:
        self._central_error = message

    def _open_settings(self) -> None:
        SettingsDialog(self._c, self).exec()
        # Логаут с очисткой кэша мог удалить беседы — пересобрать список и, если
        # открытая беседа исчезла, очистить чат.
        ids = {row["id"] for row in self._c.list_conversations()}
        if self._current is not None and self._current not in ids:
            self._current = None
            self.chat.clear()
            self._update_chat_header()
        self._sync_mode_ui()
        self.refresh_conversations()
