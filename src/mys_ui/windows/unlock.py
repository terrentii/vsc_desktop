"""Окно входа: создание или разблокировка vault."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mys_storage import VaultLocked, WrongPassword


class UnlockWindow(QWidget):
    unlocked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._creating = not controller.vault_exists()

        layout = QVBoxLayout(self)
        self.title = QLabel("Создание хранилища" if self._creating else "Разблокировка")
        layout.addWidget(self.title)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Мастер-пароль")
        layout.addWidget(self.password)

        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        self.confirm.setPlaceholderText("Повторите пароль")
        if self._creating:
            layout.addWidget(self.confirm)

        self.submit = QPushButton("Создать" if self._creating else "Войти")
        self.submit.clicked.connect(self._on_submit)
        self.password.returnPressed.connect(self._on_submit)
        layout.addWidget(self.submit)

        self.error = QLabel("")
        layout.addWidget(self.error)

    def _on_submit(self) -> None:
        self.error.setText("")
        password = self.password.text().encode("utf-8")
        try:
            if self._creating:
                if self.password.text() != self.confirm.text():
                    self.error.setText("Пароли не совпадают")
                    return
                self._c.create_vault(password)
            else:
                self._c.unlock(password)
        except WrongPassword:
            self.error.setText("Неверный пароль")
            return
        except VaultLocked as exc:
            self.error.setText(f"Заблокировано на {exc.seconds_left:.0f} с")
            return
        self.unlocked.emit()
