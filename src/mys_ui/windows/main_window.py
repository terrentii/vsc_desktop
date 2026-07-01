"""Главное окно: панель инструментов, список/чат, статус-бар.

Строку заголовка с системными кнопками даёт безрамочный хром
(``windows.frameless.FramelessWindow``) — здесь её нет."""

import mimetypes
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mys_centralized.errors import CentralizedError
from mys_decentralized import filetransfer

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


class _P2PBridge(QObject):
    """Мост из потока P2P-сервиса в UI-поток (см. ``_CentralBridge``)."""

    message = Signal(int)
    state = Signal(int, str)
    error = Signal(object, str)
    connected = Signal(int)
    connect_failed = Signal(str)
    file_sent = Signal(int)
    file_error = Signal(str)


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

        self.top = TopBar()
        root.addWidget(self.top)

        split = QSplitter(Qt.Horizontal)
        split.setObjectName("MainSplit")
        split.setHandleWidth(3)  # кобальтовая ручка = разделитель комнаты↔чат
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
        self.conversations.conversation_delete_requested.connect(self._on_delete_conversation)
        self.input.message_submitted.connect(self._on_send)
        self.input.file_submitted.connect(self._on_send_file)

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

        # Мост real-time децентрализованного (P2P) режима.
        self._p2p_bridge = _P2PBridge()
        self._p2p_bridge.message.connect(self._on_p2p_message)
        self._p2p_bridge.state.connect(self._on_p2p_state)
        self._p2p_bridge.error.connect(self._on_p2p_error)
        self._p2p_bridge.connected.connect(self._on_p2p_connected)
        self._p2p_bridge.connect_failed.connect(self._on_p2p_connect_failed)
        self._p2p_bridge.file_sent.connect(self._on_file_sent)
        self._p2p_bridge.file_error.connect(self._on_file_error)
        self._c.add_p2p_observer(
            on_message=lambda cid: self._p2p_bridge.message.emit(cid),
            on_state_change=lambda cid, st: self._p2p_bridge.state.emit(cid, st),
            on_error=lambda cid, exc: self._p2p_bridge.error.emit(cid, str(exc)),
        )

        self._sync_mode_ui()
        self.refresh_conversations()
        self._try_auto_resume()

    # --- сборка UI -------------------------------------------------------------

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
        hh.setContentsMargins(20, 14, 20, 14)
        col = QVBoxLayout()
        col.setSpacing(4)
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
        ev.setSpacing(20)
        empty_logo = QLabel()
        empty_logo.setPixmap(theme.logo_pixmap(48))
        empty_logo.setAlignment(Qt.AlignCenter)
        self._empty_label = QLabel("ВЫБЕРИТЕ ДИАЛОГ\nИЛИ НАЧНИТЕ НОВЫЙ")
        self._empty_label.setObjectName("EmptyState")
        self._empty_label.setAlignment(Qt.AlignCenter)
        ev.addWidget(empty_logo)
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
        bar.setFixedHeight(28)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        dot = QLabel()
        dot.setObjectName("StatusDot")
        dot.setFixedSize(8, 8)
        theme.block_shadow(dot, 2, 2, theme.tokens()["line"])
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

    def _peer_label(self, conversation_id: int) -> str:
        """Имя собеседника/комнаты для подписи входящих строк журнала."""
        for row in self._c.list_conversations():
            if row["id"] == conversation_id:
                return row.get("title") or f"Диалог {row['id']}"
        return "Собеседник"

    def _show_messages(self, conversation_id: int) -> None:
        self.chat.show_messages(
            self._c.list_messages(conversation_id),
            peer_label=self._peer_label(conversation_id),
        )

    def _on_select(self, conversation_id: int) -> None:
        self._current = conversation_id
        self._show_messages(conversation_id)
        self._update_chat_header()

    def _on_new(self) -> None:
        if self._c.mode == DECENTRALIZED:
            dialog = PhraseDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.phrase():
                self._start_p2p_session(dialog.phrase())
        else:
            title, ok = QInputDialog.getText(self, "Новый диалог", "Название:")
            if ok and title:
                self.add_conversation(title)
                self._set_status("Комната создана")

    def _on_send(self, text: str) -> None:
        if self._current is None:
            return
        self._c.send_message(self._current, text)
        self._show_messages(self._current)
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
            self._show_messages(conversation_id)

    def _on_central_state(self, state: str) -> None:
        self._central_state = state
        self._set_status(state)
        # Периодический ресинк/реконнект мог подтянуть новые комнаты — обновим список.
        if state in ("synced", "connected") and self._c.mode == CENTRALIZED:
            self.refresh_conversations()

    def _on_central_error(self, message: str) -> None:
        self._central_error = message

    # --- real-time P2P-режима ---------------------------------------------------

    def _start_p2p_session(self, phrase: str) -> None:
        """Установить P2P-канал в фоновом потоке (хендшейк может занять секунды —
        UI не должен зависать)."""
        if not self._c.p2p_available():
            QMessageBox.warning(self, "P2P недоступен", "P2P-сервис не сконфигурирован")
            return
        self._set_status("Подключение…")
        threading.Thread(
            target=self._p2p_connect_worker, args=(phrase,), name="mys-p2p-connect",
            daemon=True,
        ).start()

    def _p2p_connect_worker(self, phrase: str) -> None:
        try:
            conv_id = self._c.create_conversation(phrase, room_phrase=phrase)
        except Exception as exc:
            self._p2p_bridge.connect_failed.emit(str(exc))
            return
        self._p2p_bridge.connected.emit(conv_id)

    def _on_p2p_connected(self, conversation_id: int) -> None:
        self.refresh_conversations()
        self._set_status("Канал открыт")

    def _on_p2p_connect_failed(self, message: str) -> None:
        self._set_status("Ошибка подключения")
        QMessageBox.warning(self, "P2P-канал не установлен", message)

    def _on_p2p_message(self, conversation_id: int) -> None:
        self.refresh_conversations()
        if conversation_id == self._current:
            self._show_messages(conversation_id)

    def _on_p2p_state(self, conversation_id: int, state: str) -> None:
        if conversation_id == self._current:
            self._set_status(state)

    def _on_p2p_error(self, conversation_id, message: str) -> None:
        self._central_error = message
        if conversation_id is None or conversation_id == self._current:
            self._set_status("Ошибка P2P")

    # --- отправка/сохранение файлов (P2P) ---------------------------------------

    def _on_send_file(self, path: str) -> None:
        if self._current is None:
            return
        if self._c.mode != DECENTRALIZED:
            QMessageBox.information(
                self, "Недоступно", "Отправка файлов доступна только в P2P-режиме"
            )
            return
        conversation_id = self._current
        threading.Thread(
            target=self._send_file_worker, args=(conversation_id, path),
            name="mys-send-file", daemon=True,
        ).start()
        self._set_status("Отправка файла…")

    def _send_file_worker(self, conversation_id: int, path: str) -> None:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            if len(data) > filetransfer.MAX_FILE_SIZE:
                raise ValueError(
                    f"Файл больше {filetransfer.MAX_FILE_SIZE // (1024 * 1024)} МБ"
                )
            filename = os.path.basename(path)
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            self._c.send_file(conversation_id, filename, mime, data)
        except Exception as exc:
            self._p2p_bridge.file_error.emit(str(exc))
            return
        self._p2p_bridge.file_sent.emit(conversation_id)

    def _on_file_sent(self, conversation_id: int) -> None:
        self.refresh_conversations()
        if conversation_id == self._current:
            self._show_messages(conversation_id)
        self._set_status("Файл отправлен")

    def _on_file_error(self, message: str) -> None:
        self._set_status("Ошибка отправки файла")
        QMessageBox.warning(self, "Файл не отправлен", message)

    # --- удаление диалога --------------------------------------------------------

    def _on_delete_conversation(self, conversation_id: int) -> None:
        title = self._peer_label(conversation_id)
        if QMessageBox.question(
            self, "Удалить диалог",
            f"Удалить «{title}» и всю историю без возможности восстановления?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._c.delete_conversation(conversation_id)
        if self._current == conversation_id:
            self._current = None
            self.chat.clear()
            self._update_chat_header()
        self.refresh_conversations()
        self._set_status("Диалог удалён")

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
