"""Ввод секретной фразы и адреса rendezvous для P2P (фраза → PAKE/CPace → канал)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from mys_ui import theme
from mys_ui.widgets import icons
from mys_ui.widgets.brutal import BrutalButton, BrutalLineEdit
from mys_ui.windows.frameless import FramelessDialog

DEFAULT_RENDEZVOUS = "wss://soufos.ru/p2p"


class PhraseDialog(FramelessDialog):
    def __init__(self, parent=None):
        super().__init__("Новый P2P-канал", parent)
        self.setMinimumWidth(470)

        root = self.body_layout

        lbl = QLabel("ОБЩАЯ СЕКРЕТНАЯ ФРАЗА")
        lbl.setObjectName("FieldLabel")
        root.addWidget(lbl)
        self.field = BrutalLineEdit()
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

        rlbl = QLabel("RENDEZVOUS")
        rlbl.setObjectName("FieldLabel")
        root.addWidget(rlbl)
        self.rendezvous = BrutalLineEdit()
        self.rendezvous.setText(DEFAULT_RENDEZVOUS)
        root.addWidget(self.rendezvous)
        root.addSpacing(8)

        root.addWidget(self._warn_box())
        root.addSpacing(12)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_cancel = BrutalButton("Отмена", "minimal")
        self.btn_ok = BrutalButton("Открыть канал", "primary")
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
        lay.setContentsMargins(16, 12, 16, 12)
        icon = QLabel()
        icon.setPixmap(icons.pixmap(icons.warning, 22, theme.tokens()["warning"]))
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

    def rendezvous_url(self) -> str:
        return self.rendezvous.text().strip()
