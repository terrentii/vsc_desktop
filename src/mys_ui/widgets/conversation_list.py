"""Список диалогов текущего режима."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ConversationList(QWidget):
    conversation_selected = Signal(int)
    new_conversation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.btn_new = QPushButton("+ Новый диалог")
        layout.addWidget(self.list)
        layout.addWidget(self.btn_new)
        self.list.itemClicked.connect(self._on_item)
        self.btn_new.clicked.connect(self.new_conversation_requested)

    def populate(self, conversations: list[dict]) -> None:
        self.list.clear()
        for c in conversations:
            item = QListWidgetItem(c["title"] or f"Диалог {c['id']}")
            item.setData(Qt.UserRole, c["id"])
            self.list.addItem(item)

    def _on_item(self, item: QListWidgetItem) -> None:
        self.conversation_selected.emit(item.data(Qt.UserRole))
