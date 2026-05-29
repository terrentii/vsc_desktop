"""Главное окно: верхняя панель + две панели (список диалогов / чат)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mys_ui.controller import DECENTRALIZED
from mys_ui.dialogs.phrase import PhraseDialog
from mys_ui.dialogs.settings import SettingsDialog
from mys_ui.widgets.chat_view import ChatView
from mys_ui.widgets.conversation_list import ConversationList
from mys_ui.widgets.message_input import MessageInput
from mys_ui.widgets.top_bar import TopBar


class MainWindow(QWidget):
    locked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._current: int | None = None

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

        self.refresh_conversations()

    def refresh_conversations(self) -> None:
        self.conversations.populate(self._c.list_conversations())

    def add_conversation(self, title: str, *, room_phrase: str | None = None) -> None:
        self._c.create_conversation(title, room_phrase=room_phrase)
        self.refresh_conversations()

    def _on_mode(self, mode: str) -> None:
        self._c.set_mode(mode)
        self._current = None
        self.chat.clear()
        self.refresh_conversations()

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

    def _open_settings(self) -> None:
        SettingsDialog(self._c, self).exec()
