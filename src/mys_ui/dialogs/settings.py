"""Минимальные настройки: смена мастер-пароля."""

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from mys_storage import WrongPassword


class SettingsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self.setWindowTitle("Настройки")
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.old_pw = QLineEdit()
        self.old_pw.setEchoMode(QLineEdit.Password)
        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.Password)
        form.addRow("Старый пароль", self.old_pw)
        form.addRow("Новый пароль", self.new_pw)
        layout.addLayout(form)

        self.btn_change = QPushButton("Сменить пароль")
        self.btn_change.clicked.connect(self._change)
        layout.addWidget(self.btn_change)

        self.status = QLabel("")
        layout.addWidget(self.status)

    def _change(self) -> None:
        try:
            self._c.change_password(
                self.old_pw.text().encode("utf-8"),
                self.new_pw.text().encode("utf-8"),
            )
            self.status.setText("Пароль изменён")
        except WrongPassword:
            self.status.setText("Неверный старый пароль")
