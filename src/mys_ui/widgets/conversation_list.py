"""Боковая панель: заголовок + счётчик, список диалогов, кнопка нового диалога."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme
from mys_ui.controller import DECENTRALIZED


class ConversationList(QWidget):
    conversation_selected = Signal(int)
    new_conversation_requested = Signal()
    conversation_delete_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._mode = DECENTRALIZED

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("SidebarHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
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
        self.list.setFont(theme.mono_font(16))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list, 1)

        from mys_ui.widgets.brutal import BrutalButton

        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 12)
        # DS create-btn: чернильное лицо + кобальтовая тень
        self.btn_new = BrutalButton("+ Новый диалог", "ink", shadow="accent")
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

    def _on_context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_delete = menu.addAction("Удалить диалог")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen == act_delete:
            self.conversation_delete_requested.emit(item.data(Qt.UserRole))
