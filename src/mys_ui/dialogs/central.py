"""Диалог входа в централизованный режим: сервер, логин, пароль, Вход/Регистрация."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit

from mys_ui.widgets.brutal import BrutalButton, BrutalLineEdit
from mys_ui.windows.frameless import FramelessDialog

DEFAULT_SERVER = "https://soufos.ru"


class CentralLoginDialog(FramelessDialog):
    def __init__(self, parent=None, *, default_url: str = DEFAULT_SERVER):
        super().__init__("Вход — Центр", parent)
        self.setMinimumWidth(430)
        self._register = False

        root = self.body_layout
        root.setSpacing(8)

        self.server = BrutalLineEdit(default_url)
        self.username = BrutalLineEdit()
        self.username.setPlaceholderText("terrentii")
        self.password = BrutalLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("••••••••")
        for label, field in (
            ("СЕРВЕР", self.server),
            ("ЛОГИН", self.username),
            ("ПАРОЛЬ", self.password),
        ):
            lbl = QLabel(label)
            lbl.setObjectName("FieldLabel")
            root.addWidget(lbl)
            root.addWidget(field)
            root.addSpacing(8)

        buttons = QHBoxLayout()
        self.btn_login = BrutalButton("Войти", "primary")
        self.btn_register = BrutalButton("Регистрация", "default")
        self.btn_cancel = BrutalButton("Отмена", "minimal")
        buttons.addWidget(self.btn_login, 1)
        buttons.addWidget(self.btn_register, 1)
        buttons.addWidget(self.btn_cancel)
        root.addSpacing(8)
        root.addLayout(buttons)

        self.btn_login.clicked.connect(self._accept_login)
        self.btn_register.clicked.connect(self._accept_register)
        self.btn_cancel.clicked.connect(self.reject)

    def _accept_login(self) -> None:
        self._register = False
        self.accept()

    def _accept_register(self) -> None:
        self._register = True
        self.accept()

    def is_register(self) -> bool:
        return self._register

    def values(self) -> tuple[str, str, str]:
        return (
            self.server.text().strip(),
            self.username.text().strip(),
            self.password.text(),
        )
