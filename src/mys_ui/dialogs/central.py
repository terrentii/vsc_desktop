"""Диалог входа в централизованный режим: сервер, логин, пароль, Вход/Регистрация."""

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

DEFAULT_SERVER = "https://soufos.ru"


class CentralLoginDialog(QDialog):
    def __init__(self, parent=None, *, default_url: str = DEFAULT_SERVER):
        super().__init__(parent)
        self.setWindowTitle("Вход — Центр")
        self._register = False

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.server = QLineEdit(default_url)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Сервер:", self.server)
        form.addRow("Логин:", self.username)
        form.addRow("Пароль:", self.password)
        root.addLayout(form)

        buttons = QHBoxLayout()
        self.btn_login = QPushButton("Вход")
        self.btn_register = QPushButton("Регистрация")
        self.btn_cancel = QPushButton("Отмена")
        buttons.addWidget(self.btn_login)
        buttons.addWidget(self.btn_register)
        buttons.addStretch()
        buttons.addWidget(self.btn_cancel)
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
