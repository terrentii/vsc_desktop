"""Главное окно: верхняя панель + две панели (список диалогов / чат)."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mys_centralized.errors import CentralizedError

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


class MainWindow(QWidget):
    locked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._current: int | None = None
        self._central_error: str | None = None
        self._central_state: str | None = None

        root = QVBoxLayout(self)
        self.top = TopBar()
        root.addWidget(self.top)

        split = QSplitter(Qt.Horizontal)
        self.conversations = ConversationList()
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.chat = ChatView()
        self.input = MessageInput()
        right_layout.addWidget(self.chat)
        right_layout.addWidget(self.input)
        split.addWidget(self.conversations)
        split.addWidget(right)
        root.addWidget(split)

        self.top.mode_changed.connect(self._on_mode)
        self.top.lock_requested.connect(self.locked)
        self.top.settings_requested.connect(self._open_settings)
        self.conversations.conversation_selected.connect(self._on_select)
        self.conversations.new_conversation_requested.connect(self._on_new)
        self.input.message_submitted.connect(self._on_send)

        # Мост real-time централизованного режима.
        self._bridge = _CentralBridge()
        self._bridge.message.connect(self._on_central_message)
        self._bridge.state.connect(self._on_central_state)
        self._bridge.error.connect(self._on_central_error)
        self._c.add_central_observer(
            on_message=lambda cid, lid: self._bridge.message.emit(cid, lid),
            on_state_change=lambda st: self._bridge.state.emit(st),
            on_error=lambda exc: self._bridge.error.emit(str(exc)),
        )

        self.refresh_conversations()

    def refresh_conversations(self) -> None:
        self.conversations.populate(self._c.list_conversations())

    def add_conversation(self, title: str, *, room_phrase: str | None = None) -> None:
        self._c.create_conversation(title, room_phrase=room_phrase)
        self.refresh_conversations()

    # --- режимы ----------------------------------------------------------------

    def _on_mode(self, mode: str) -> None:
        self._c.set_mode(mode)
        self._current = None
        self.chat.clear()
        if (
            mode == CENTRALIZED
            and self._c.central_available()
            and self._c.central_session() is None
        ):
            self._central_login()
        self.refresh_conversations()

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
        self.refresh_conversations()
        return True

    # --- выбор/отправка/создание ----------------------------------------------

    def _on_select(self, conversation_id: int) -> None:
        self._current = conversation_id
        self.chat.show_messages(self._c.list_messages(conversation_id))

    def _on_new(self) -> None:
        if self._c.mode == DECENTRALIZED:
            dialog = PhraseDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.phrase():
                self.add_conversation(dialog.phrase(), room_phrase=dialog.phrase())
        else:
            title, ok = QInputDialog.getText(self, "Новый диалог", "Название:")
            if ok and title:
                self.add_conversation(title)

    def _on_send(self, text: str) -> None:
        if self._current is None:
            return
        self._c.send_message(self._current, text)
        self.chat.show_messages(self._c.list_messages(self._current))

    # --- real-time централизованного режима ------------------------------------

    def _on_central_message(self, conversation_id: int, _local_id: int) -> None:
        self.refresh_conversations()  # могла появиться новая комната
        if conversation_id == self._current:
            self.chat.show_messages(self._c.list_messages(conversation_id))

    def _on_central_state(self, state: str) -> None:
        self._central_state = state

    def _on_central_error(self, message: str) -> None:
        self._central_error = message

    def _open_settings(self) -> None:
        SettingsDialog(self._c, self).exec()
