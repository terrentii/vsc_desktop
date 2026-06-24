"""Диалог входа в централизованный режим: сервер, логин, пароль, Вход/Регистрация."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

DEFAULT_SERVER = "https://soufos.ru"


class CentralLoginDialog(QDialog):
    def __init__(self, parent=None, *, default_url: str = DEFAULT_SERVER):
        super().__init__(parent)
        self.setWindowTitle("Вход — Центр")
        self.setMinimumWidth(430)
        self._register = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(6)

        title = QLabel("ВХОД — ЦЕНТР")
        title.setObjectName("DialogTitle")
        root.addWidget(title)
        root.addSpacing(12)

        self.server = QLineEdit(default_url)
        self.username = QLineEdit()
        self.username.setPlaceholderText("terrentii")
        self.password = QLineEdit()
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
        self.btn_login = QPushButton("ВОЙТИ")
        self.btn_login.setObjectName("PrimaryBtn")
        self.btn_register = QPushButton("РЕГИСТРАЦИЯ")
        self.btn_register.setObjectName("PrimaryBtn")
        self.btn_cancel = QPushButton("ОТМЕНА")
        self.btn_cancel.setObjectName("GhostBtn")
        for b in (self.btn_login, self.btn_register, self.btn_cancel):
            b.setCursor(Qt.PointingHandCursor)
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
