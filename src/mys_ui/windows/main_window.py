"""Главное окно: панель инструментов, список/чат, статус-бар.

Строку заголовка с системными кнопками даёт безрамочный хром
(``windows.frameless.FramelessWindow``) — здесь её нет."""

import mimetypes
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mys_centralized.errors import CentralizedError
from mys_decentralized import filetransfer

from mys_ui import prefs, theme
from mys_ui.controller import CENTRALIZED, DECENTRALIZED
from mys_ui.dialogs import common
from mys_ui.dialogs.central import CentralLoginDialog
from mys_ui.dialogs.phrase import PhraseDialog
from mys_ui.dialogs.settings import SettingsDialog
from mys_ui.widgets.chat_view import ChatView
from mys_ui.widgets.conversation_list import ConversationList
from mys_ui.widgets.message_input import MessageInput
from mys_ui.widgets.p2p_banner import P2POfflineBanner
from mys_ui.widgets.top_bar import TopBar

# Единый лимит ожидания пира (новый канал и реконнект) — 5 минут; используется и
# для реального таймаута сервиса, и для обратного отсчёта в P2POfflineBanner,
# чтобы визуальный таймер не мог разойтись с фактическим.
_P2P_TIMEOUT_S = 300


class _CentralBridge(QObject):
    """Мост из потока централизованного сервиса в UI-поток через Qt-сигналы.

    Колбэки сервиса (фоновый поток) лишь вызывают ``emit``; Qt доставляет их в
    UI-поток (queued-соединение), где слоты безопасно трогают виджеты."""

    message = Signal(int, int)
    state = Signal(str)
    error = Signal(str)
    resumed = Signal(bool)
    media_ready = Signal(int)
    login_finished = Signal(bool)
    op_done = Signal(bool, str)  # правка/удаление сообщения: успех, текст ошибки


class _P2PBridge(QObject):
    """Мост из потока P2P-сервиса в UI-поток (см. ``_CentralBridge``)."""

    message = Signal(int)
    state = Signal(int, str)
    error = Signal(object, str)
    connected = Signal(int)
    connect_failed = Signal(int, str)
    file_sent = Signal(int)
    file_error = Signal(str)


class MainWindow(QWidget):
    locked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._current: int | None = None
        # Активный «ответ на…»: {"wire","sender","snippet"} для следующей отправки.
        self._reply: dict | None = None
        self._central_error: str | None = None
        self._central_state: str | None = None
        self._pending_fetches: set[int] = set()
        # Сообщения, для которых автозагрузка картинки уже провалилась в этой
        # сессии приложения — не долбим сеть повторно на каждой перерисовке.
        self._media_fetch_failed: set[int] = set()

        # P2P «онлайн»/реконнект: online — есть ли прямо сейчас живая сессия
        # (обновляется по колбэкам connected/disconnected, в т.ч. автоматическим
        # при обрыве, см. P2PService._handle_disconnect); connecting — идёт
        # попытка подключения (conv_id -> абсолютный дедлайн time.monotonic());
        # banner_dismissed_for — беседа, для которой в ЭТОМ визите нажали
        # «прочитать переписку» (плашка снова появится при следующем входе).
        self._p2p_online: dict[int, bool] = {}
        self._p2p_connecting: dict[int, float] = {}
        self._p2p_banner_dismissed_for: int | None = None

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
        self.conversations.conversation_rename_requested.connect(self._on_rename_conversation)
        self.input.message_submitted.connect(self._on_send)
        self.input.file_submitted.connect(self._on_send_file)
        self.chat.media_fetch_requested.connect(self._on_media_fetch_requested)
        self.chat.reply_requested.connect(self._on_reply_requested)
        self.chat.edit_requested.connect(self._on_edit_requested)
        self.chat.delete_requested.connect(self._on_delete_requested)
        self.input.reply_cancelled.connect(self._on_reply_cancelled)

        # Мост real-time централизованного режима.
        self._bridge = _CentralBridge()
        self._bridge.message.connect(self._on_central_message)
        self._bridge.state.connect(self._on_central_state)
        self._bridge.error.connect(self._on_central_error)
        self._bridge.resumed.connect(self._on_resumed)
        self._bridge.media_ready.connect(self._on_media_ready)
        self._bridge.login_finished.connect(self._on_login_finished)
        self._bridge.op_done.connect(self._on_op_done)
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
        self.p2p_banner.reconnect_requested.connect(self._on_p2p_reconnect_requested)
        self.p2p_banner.read_history_requested.connect(self._on_p2p_read_history_requested)
        self._p2p_bridge.file_sent.connect(self._on_file_sent)
        self._p2p_bridge.file_error.connect(self._on_file_error)
        self._c.add_p2p_observer(
            on_message=lambda cid: self._p2p_bridge.message.emit(cid),
            on_state_change=lambda cid, st: self._p2p_bridge.state.emit(cid, st),
            on_error=lambda cid, exc: self._p2p_bridge.error.emit(cid, str(exc)),
        )

        # Восстановить последний режим (P2P/«Центр») — без сигнала: форма входа
        # при старте не нужна, сессию поднимет _try_auto_resume.
        saved_mode = prefs.load_mode(self._c.mode)
        if saved_mode != self._c.mode:
            self._c.set_mode(saved_mode)
        self.top.set_mode(self._c.mode)

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
        self._chat_online = QLabel("")  # только P2P: «● В СЕТИ» / «● НЕ В СЕТИ»
        self._chat_online.setObjectName("ChatOnline")
        self._chat_online.hide()
        col.addWidget(self._chat_name)
        col.addWidget(self._chat_sub)
        col.addWidget(self._chat_online)
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
        self._chat_stack.addWidget(chat_box)  # индекс 1

        # оверлей «собеседник офлайн» / ожидание подключения (P2P, индекс 2)
        self.p2p_banner = P2POfflineBanner()
        self._chat_stack.addWidget(self.p2p_banner)

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
        prefs.save_mode(mode)  # режим переживает перезапуск
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
        # Вход + первичный синк занимают секунды — в фоновом потоке, чтобы UI не
        # замирал (результат прилетит сигналом login_finished).
        self._set_status("Вход…")
        threading.Thread(
            target=self._login_worker,
            args=(url, username, password, dialog.is_register()),
            name="mys-central-login", daemon=True,
        ).start()

    def _login_worker(self, url, username, password, register: bool) -> None:
        ok = self._perform_central_login(url, username, password, register)
        self._bridge.login_finished.emit(ok)

    def _on_login_finished(self, ok: bool) -> None:
        if ok:
            self._sync_mode_ui()
            self.refresh_conversations()
            self._set_status("Вход выполнен")
        else:
            self._set_status("Вход не выполнен")
            common.warn(self, "Вход не выполнен", self._central_error or "Ошибка")

    def _perform_central_login(self, url, username, password, register: bool) -> bool:
        """Выполнить вход (без модальных окон и Qt) — возвращает успех. Тестируемо.

        Зовётся из фонового потока — виджеты здесь трогать нельзя."""
        self._central_error = None
        try:
            self._c.central_login(url, username, password, register=register)
        except CentralizedError as exc:
            self._central_error = str(exc)
            return False
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

    def add_conversation(self, title: str) -> None:
        self._c.create_conversation(title)
        self.refresh_conversations()

    def _peer_label(self, conversation_id: int) -> str:
        """Имя собеседника/комнаты для подписи входящих строк журнала."""
        for row in self._c.list_conversations():
            if row["id"] == conversation_id:
                return row.get("title") or f"Диалог {row['id']}"
        return "Собеседник"

    def _show_messages(self, conversation_id: int) -> None:
        rows = self._c.list_messages(conversation_id)
        own_label, own_sender = "я", None
        if self._c.mode == CENTRALIZED:
            sess = self._c.central_session()
            if sess is not None:
                # Свои сообщения, отправленные из веба, приходят «входящими» с
                # нашим логином — рисуем и управляем ими как своими.
                own_label = own_sender = sess.username
        self.chat.show_messages(
            rows, peer_label=self._peer_label(conversation_id),
            own_label=own_label, own_sender=own_sender,
        )
        # Автозагрузка картинок при открытии беседы (паритет с вебом — там это
        # обычный <img src=...>); обычные файлы остаются по требованию (клик).
        for row in rows:
            if (
                row.get("kind") == "image" and row["body"] is None
                and row["id"] not in self._media_fetch_failed
            ):
                self._on_media_fetch_requested(row["id"])

    def _on_select(self, conversation_id: int) -> None:
        if self._current != conversation_id:
            self.input.clear_reply()  # «ответ на…» не переносится между беседами
        self._current = conversation_id
        # Плашка «собеседник офлайн» должна появляться заново при каждом входе
        # в беседу — сбрасываем дисмисс прошлого визита (см. P2POfflineBanner).
        self._p2p_banner_dismissed_for = None
        self._show_messages(conversation_id)
        self._update_chat_header()

    def _on_new(self) -> None:
        if self._c.mode == DECENTRALIZED:
            dialog = PhraseDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.phrase():
                self._begin_p2p_connect(phrase=dialog.phrase())
        else:
            title, ok = common.ask_text(self, "Новый диалог", "НАЗВАНИЕ")
            if ok and title:
                self.add_conversation(title)
                self._set_status("Комната создана")

    def _on_send(self, text: str) -> None:
        if self._current is None:
            return
        reply = self._reply if self._c.mode == CENTRALIZED else None
        self._c.send_message(self._current, text, reply=reply)
        self.input.clear_reply()
        self._show_messages(self._current)
        self._set_status("Сообщение отправлено")

    # --- действия над сообщениями «Центра» (ответить/изменить/удалить) -----------

    def _find_message(self, local_id: int) -> dict | None:
        if self._current is None:
            return None
        for row in self._c.list_messages(self._current):
            if row["id"] == local_id:
                return row
        return None

    def _is_own_row(self, row: dict) -> bool:
        """Своё сообщение: исходящее либо входящее с логином нашего аккаунта
        (собственные сообщения, отправленные из веб-версии)."""
        if row["direction"] == "out":
            return True
        if self._c.mode == CENTRALIZED:
            sess = self._c.central_session()
            return sess is not None and row.get("sender") == sess.username
        return False

    def _row_author(self, row: dict) -> str:
        if row.get("sender"):
            return row["sender"]
        if row["direction"] == "out":
            sess = self._c.central_session()
            return sess.username if sess is not None else "я"
        return self._peer_label(row["conversation_id"])

    @staticmethod
    def _row_snippet(row: dict) -> str:
        """Короткая цитата строки: вложения не «расшифровываем» в байты."""
        kind = row.get("kind")
        if kind == "image":
            return "Изображение"
        if kind == "file":
            return row.get("filename") or "Файл"
        return (row["body"].decode("utf-8", "replace") if row["body"] else "")[:60]

    def _on_reply_requested(self, local_id: int) -> None:
        row = self._find_message(local_id)
        if row is None or row.get("wire_seq") is None:
            return
        snippet = self._row_snippet(row)
        author = self._row_author(row)
        self._reply = {"wire": row["wire_seq"], "sender": author, "snippet": snippet}
        self.input.set_reply(author, snippet)

    def _on_reply_cancelled(self) -> None:
        self._reply = None

    def _on_edit_requested(self, local_id: int) -> None:
        row = self._find_message(local_id)
        if row is None or not self._is_own_row(row):
            return
        current = row["body"].decode("utf-8", "replace") if row["body"] else ""
        text, ok = common.ask_multiline(self, "Изменить сообщение", "ТЕКСТ", current)
        text = text.strip()
        if not ok or not text or text == current:
            return
        self._run_message_op(lambda: self._c.central_edit_message(local_id, text))

    def _on_delete_requested(self, local_id: int) -> None:
        row = self._find_message(local_id)
        if row is None or not self._is_own_row(row):
            return
        if not common.confirm(
            self, "Удалить сообщение", "Удалить сообщение у всех участников?",
            ok_label="Удалить", danger=True,
        ):
            return
        self._run_message_op(lambda: self._c.central_delete_message(local_id))

    def _run_message_op(self, op) -> None:
        """Сетевую правку/удаление — в фоне; результат сигналом op_done."""
        def worker():
            try:
                op()
            except Exception as exc:
                self._bridge.op_done.emit(False, str(exc))
                return
            self._bridge.op_done.emit(True, "")
        threading.Thread(target=worker, name="mys-central-op", daemon=True).start()

    def _on_op_done(self, ok: bool, error: str) -> None:
        if self._current is not None:
            self._show_messages(self._current)
        if ok:
            self._set_status("Готово")
        else:
            self._set_status("Ошибка")
            common.warn(self, "Не удалось выполнить", error or "Ошибка")

    def _update_chat_header(self) -> None:
        """Показать шапку выбранного диалога либо пустое состояние."""
        # Действия над сообщениями — только «Центр» с активной сессией.
        self.chat.actions_enabled = (
            self._c.mode == CENTRALIZED and self._c.central_session() is not None
        )
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
            self._update_p2p_online_label()
        else:
            self._chat_sub.setText(f"ROOM {room}" if room else "ЦЕНТР")
            self._chat_badge.setText("soufos.ru")
            self._chat_online.hide()
        self._chat_header.show()
        self._update_p2p_stack_page()

    def _update_p2p_online_label(self) -> None:
        """Точка «В СЕТИ»/«НЕ В СЕТИ» рядом с именем беседы (только P2P)."""
        online = self._p2p_online.get(self._current, False)
        t = theme.tokens()
        if online:
            self._chat_online.setText("● В СЕТИ")
            self._chat_online.setStyleSheet(f"color: {t['success']};")
        else:
            self._chat_online.setText("● НЕ В СЕТИ")
            self._chat_online.setStyleSheet(f"color: {t['warn']};")
        self._chat_online.show()

    def _update_p2p_stack_page(self) -> None:
        """Решить, что показать в области чата: сам чат, оверлей ожидания пира
        (идёт подключение/реконнект) или плашку «офлайн» (P2P, не онлайн).

        «Прочитать переписку» имеет приоритет над остальным: снимает оверлей
        для этого визита, даже если подключение всё ещё идёт в фоне."""
        if self._c.mode != DECENTRALIZED:
            self._chat_stack.setCurrentIndex(1)
            return
        conv_id = self._current
        if self._p2p_banner_dismissed_for == conv_id:
            self._chat_stack.setCurrentIndex(1)
            return
        deadline = self._p2p_connecting.get(conv_id)
        if deadline is not None:
            remaining = max(0, round(deadline - time.monotonic()))
            self.p2p_banner.start_countdown(remaining)
            self._chat_stack.setCurrentIndex(2)
            return
        if self._p2p_online.get(conv_id, False):
            self._chat_stack.setCurrentIndex(1)
        else:
            self.p2p_banner.set_idle()
            self._chat_stack.setCurrentIndex(2)

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

    def _begin_p2p_connect(
        self, *, phrase: str | None = None, conversation_id: int | None = None,
    ) -> None:
        """Единая точка входа в подключение P2P — новый канал (``phrase``) или
        реконнект уже известной беседы (``conversation_id``, кнопка «Выйти на
        связь»). Показывает окно ожидания с обратным отсчётом (5 минут) и
        запускает попытку в фоновом потоке — хендшейк может занять время, UI не
        должен зависать."""
        if not self._c.p2p_available():
            common.warn(self, "P2P недоступен", "P2P-сервис не сконфигурирован")
            return
        if phrase is not None:
            # Резолвим conv_id локально (без сети) — сразу показываем окно
            # ожидания для ЭТОЙ беседы, не дожидаясь хендшейка.
            try:
                conv_id = self._c.p2p_resolve_conversation(phrase)
            except Exception as exc:
                common.warn(self, "P2P-канал не установлен", str(exc))
                return
        else:
            conv_id = conversation_id
        if conv_id in self._p2p_connecting:
            return  # уже идёт попытка для этой беседы — повторный клик игнорируем
        self._p2p_connecting[conv_id] = time.monotonic() + _P2P_TIMEOUT_S
        self.refresh_conversations()
        self.conversations.select(conv_id)
        self._current = conv_id
        self._show_messages(conv_id)
        self._update_chat_header()
        self._set_status("Подключение…")
        threading.Thread(
            target=self._p2p_connect_worker, args=(conv_id, phrase),
            name="mys-p2p-connect", daemon=True,
        ).start()

    def _p2p_connect_worker(self, conv_id: int, phrase: str | None) -> None:
        try:
            if phrase is not None:
                self._c.p2p_start_session(phrase, timeout=_P2P_TIMEOUT_S)
            else:
                self._c.p2p_reconnect(conv_id, timeout=_P2P_TIMEOUT_S)
        except Exception as exc:
            self._p2p_bridge.connect_failed.emit(conv_id, str(exc))
            return
        self._p2p_bridge.connected.emit(conv_id)

    def _on_p2p_connected(self, conversation_id: int) -> None:
        self._p2p_connecting.pop(conversation_id, None)
        self._p2p_online[conversation_id] = True
        self.refresh_conversations()
        if conversation_id == self._current:
            self._show_messages(conversation_id)  # мог прийти prime и т.п.
            self._update_chat_header()
        self._set_status("Канал открыт")

    def _on_p2p_connect_failed(self, conversation_id: int, message: str) -> None:
        self._p2p_connecting.pop(conversation_id, None)
        self._p2p_online[conversation_id] = False
        self._set_status("Ошибка подключения")
        if conversation_id == self._current:
            # _update_chat_header() сама переключит плашку в idle (без note) —
            # note выставляем ПОСЛЕ, иначе он тут же перезатрётся.
            self._update_chat_header()
            self.p2p_banner.set_idle(note=message)

    def _on_p2p_reconnect_requested(self) -> None:
        """Нажата «Выйти на связь» в плашке офлайн-беседы."""
        if self._current is not None:
            self._begin_p2p_connect(conversation_id=self._current)

    def _on_p2p_read_history_requested(self) -> None:
        """«Прочитать переписку» — снять оверлей для этого визита, не трогая
        попытку подключения (если она идёт, продолжится в фоне)."""
        if self._current is not None:
            self._p2p_banner_dismissed_for = self._current
            self._update_chat_header()

    def _on_p2p_message(self, conversation_id: int) -> None:
        self._p2p_online[conversation_id] = True
        self.refresh_conversations()
        if conversation_id == self._current:
            self._update_chat_header()
            self._show_messages(conversation_id)

    def _on_p2p_state(self, conversation_id: int, state: str) -> None:
        """``state`` — «connected»/«disconnected» (в т.ч. автоматически при
        обрыве транспорта, см. ``P2PService._handle_disconnect``)."""
        if state == "connected":
            self._p2p_online[conversation_id] = True
        elif state == "disconnected":
            self._p2p_online[conversation_id] = False
        if conversation_id == self._current:
            self._set_status(state)
            if self._c.mode == DECENTRALIZED:
                # Обновляет точку «онлайн»; если чат сейчас читают (плашка уже
                # отпущена в этом визите — см. _p2p_banner_dismissed_for), живой
                # разрыв не выдёргивает плашку поверх открытой переписки.
                self._update_chat_header()

    def _on_p2p_error(self, conversation_id, message: str) -> None:
        self._central_error = message
        if conversation_id is None or conversation_id == self._current:
            self._set_status("Ошибка P2P")

    # --- отправка/сохранение файлов (P2P + «Центр») ------------------------------

    def _on_send_file(self, path: str) -> None:
        if self._current is None:
            return
        conversation_id = self._current
        if self._c.mode == DECENTRALIZED:
            threading.Thread(
                target=self._send_file_worker, args=(conversation_id, path),
                name="mys-send-file", daemon=True,
            ).start()
        elif self._c.mode == CENTRALIZED:
            if self._c.central_session() is None:
                common.warn(self, "Недоступно", "Войдите в «Центр», чтобы отправлять файлы")
                return
            threading.Thread(
                target=self._send_central_file_worker, args=(conversation_id, path),
                name="mys-send-central-file", daemon=True,
            ).start()
        else:
            return
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

    def _send_central_file_worker(self, conversation_id: int, path: str) -> None:
        from mys_centralized import media

        try:
            filename = os.path.basename(path)
            media.validate_extension(filename)
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            with open(path, "rb") as fh:
                data = fh.read()
            if len(data) > media.MAX_MEDIA_SIZE:
                raise ValueError(f"Файл больше {media.MAX_MEDIA_SIZE // (1024 * 1024)} МБ")
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
        common.warn(self, "Файл не отправлен", message)

    # --- ленивая докачка вложений «Центра» ---------------------------------------

    def _on_media_fetch_requested(self, message_id: int) -> None:
        if message_id in self._pending_fetches:
            return
        self._pending_fetches.add(message_id)
        threading.Thread(
            target=self._fetch_media_worker, args=(message_id,),
            name="mys-fetch-media", daemon=True,
        ).start()

    def _fetch_media_worker(self, message_id: int) -> None:
        ok = False
        try:
            self._c.fetch_media(message_id)
            ok = True
        except Exception:
            pass  # best-effort — строка останется с плейсхолдером «нажмите»/«загрузка»
        finally:
            if not ok:
                self._media_fetch_failed.add(message_id)
            self._bridge.media_ready.emit(message_id)

    def _on_media_ready(self, message_id: int) -> None:
        self._pending_fetches.discard(message_id)
        if self._current is not None:
            self._show_messages(self._current)

    # --- удаление диалога --------------------------------------------------------

    def _on_rename_conversation(self, conversation_id: int) -> None:
        current = self._peer_label(conversation_id)
        title, ok = common.ask_text(
            self, "Переименовать канал", "НАЗВАНИЕ", current, ok_label="Сохранить"
        )
        title = title.strip()
        if not ok or not title or title == current:
            return
        self._c.rename_conversation(conversation_id, title)
        self.refresh_conversations()
        if self._current == conversation_id:
            self._update_chat_header()
        self._set_status("Канал переименован")

    def _on_delete_conversation(self, conversation_id: int) -> None:
        title = self._peer_label(conversation_id)
        if not common.confirm(
            self, "Удалить диалог",
            f"Удалить «{title}» и всю историю без возможности восстановления?",
            ok_label="Удалить", danger=True,
        ):
            return
        self._c.delete_conversation(conversation_id)
        self._p2p_online.pop(conversation_id, None)
        self._p2p_connecting.pop(conversation_id, None)
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
