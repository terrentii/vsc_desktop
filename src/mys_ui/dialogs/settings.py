"""Настройки: смена мастер-пароля и аккаунт «Центра»."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
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

        # --- секция «Центр» (только если режим сконфигурирован) ---------------
        if self._c.central_available():
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            layout.addWidget(sep)
            layout.addWidget(QLabel("Аккаунт «Центр»"))

            self.wipe_on_logout = QCheckBox("Стирать историю «Центра» при выходе")
            self.wipe_on_logout.setChecked(self._c.central_wipe_on_logout())
            self.wipe_on_logout.toggled.connect(self._c.set_central_wipe_on_logout)
            layout.addWidget(self.wipe_on_logout)

            self.btn_logout = QPushButton("Выйти из аккаунта")
            self.btn_logout.setEnabled(self._c.central_session() is not None)
            self.btn_logout.clicked.connect(self._logout)
            layout.addWidget(self.btn_logout)

    def _change(self) -> None:
        try:
            self._c.change_password(
                self.old_pw.text().encode("utf-8"),
                self.new_pw.text().encode("utf-8"),
            )
            self.status.setText("Пароль изменён")
        except WrongPassword:
            self.status.setText("Неверный старый пароль")

    def _logout(self) -> None:
        self._c.central_logout()
        self.btn_logout.setEnabled(False)
        self.status.setText("Выход из «Центра» выполнен")
