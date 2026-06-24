"""Боковая панель: заголовок + счётчик, список диалогов, кнопка нового диалога."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme
from mys_ui.controller import DECENTRALIZED


class ConversationList(QWidget):
    conversation_selected = Signal(int)
    new_conversation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._mode = DECENTRALIZED

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("SidebarHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 13, 16, 13)
        self.title = QLabel("ДИАЛОГИ")
        self.title.setObjectName("ListTitle")
        self.count = QLabel("0")
        self.count.setObjectName("ListCount")
        h.addWidget(self.title)
        h.addStretch()
        h.addWidget(self.count)
        layout.addWidget(header)

        self.list = QListWidget()
        self.list.setObjectName("ConvList")
        self.list.setFont(theme.mono_font(12))
        layout.addWidget(self.list, 1)

        from PySide6.QtWidgets import QPushButton

        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 12)
        self.btn_new = QPushButton("+ НОВЫЙ ДИАЛОГ")
        self.btn_new.setObjectName("PrimaryBtn")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        wl.addWidget(self.btn_new)
        layout.addWidget(wrap)

        self.list.itemClicked.connect(self._on_item)
        self.btn_new.clicked.connect(self.new_conversation_requested)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.title.setText("КАНАЛЫ" if mode == DECENTRALIZED else "КОМНАТЫ")
        self.btn_new.setText(
            "+ НОВЫЙ КАНАЛ" if mode == DECENTRALIZED else "+ НОВАЯ КОМНАТА"
        )

    def populate(self, conversations: list[dict]) -> None:
        self.list.clear()
        for c in conversations:
            item = QListWidgetItem(c["title"] or f"Диалог {c['id']}")
            item.setData(Qt.UserRole, c["id"])
            self.list.addItem(item)
        self.count.setText(str(len(conversations)))

    def _on_item(self, item: QListWidgetItem) -> None:
        self.conversation_selected.emit(item.data(Qt.UserRole))
