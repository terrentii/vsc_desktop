"""Ввод общей секретной фразы для P2P (фраза → PAKE/CPace → канал)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme


class PhraseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый P2P-канал")
        self.setMinimumWidth(470)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(8)

        title = QLabel("НОВЫЙ P2P-КАНАЛ")
        title.setObjectName("DialogTitle")
        root.addWidget(title)
        root.addSpacing(12)

        lbl = QLabel("ОБЩАЯ СЕКРЕТНАЯ ФРАЗА")
        lbl.setObjectName("FieldLabel")
        root.addWidget(lbl)
        self.field = QLineEdit()
        self.field.setPlaceholderText("например: северный ветер сорок один")
        root.addWidget(self.field)

        hint = QLabel(
            "Из фразы выводится ключ (PAKE/CPace) и room_id. "
            "Сервер не видит ни фразу, ни текст."
        )
        hint.setObjectName("StatusMono")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addSpacing(8)

        root.addWidget(self._warn_box())
        root.addSpacing(10)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_cancel = QPushButton("ОТМЕНА")
        self.btn_cancel.setObjectName("GhostBtn")
        self.btn_ok = QPushButton("ОТКРЫТЬ КАНАЛ")
        self.btn_ok.setObjectName("PrimaryBtn")
        for b in (self.btn_cancel, self.btn_ok):
            b.setCursor(Qt.PointingHandCursor)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_ok)
        root.addLayout(buttons)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.field.returnPressed.connect(self.accept)

    def _warn_box(self) -> QWidget:
        box = QWidget()
        box.setObjectName("WarnBox")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        icon = QLabel("⚠")
        icon.setStyleSheet(f"color: {theme.tokens()['warning']}; background: transparent;")
        icon.setAlignment(Qt.AlignTop)
        text = QLabel(
            "Передайте фразу собеседнику только по защищённому каналу. "
            "Неверная фраза или MITM — соединение разрывается с предупреждением."
        )
        text.setObjectName("WarnBoxText")
        text.setWordWrap(True)
        lay.addWidget(icon)
        lay.addSpacing(8)
        lay.addWidget(text, 1)
        return box

    def phrase(self) -> str:
        return self.field.text().strip()
