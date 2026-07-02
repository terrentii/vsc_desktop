"""Настройки: смена мастер-пароля, тема и аккаунт «Центра»."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)

from mys_storage import WrongPassword

from mys_ui import theme
from mys_ui.widgets.brutal import BrutalButton, BrutalCheckBox, BrutalLineEdit
from mys_ui.windows.frameless import FramelessDialog


class SettingsDialog(FramelessDialog):
    def __init__(self, controller, parent=None):
        super().__init__("Настройки", parent)
        self._c = controller
        self.setMinimumWidth(440)

        layout = self.body_layout

        layout.addWidget(self._section("МАСТЕР-ПАРОЛЬ"))
        self.old_pw = BrutalLineEdit()
        self.old_pw.setEchoMode(QLineEdit.Password)
        self.new_pw = BrutalLineEdit()
        self.new_pw.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._label("СТАРЫЙ ПАРОЛЬ"))
        layout.addWidget(self.old_pw)
        layout.addWidget(self._label("НОВЫЙ ПАРОЛЬ"))
        layout.addWidget(self.new_pw)
        layout.addSpacing(8)

        self.btn_change = BrutalButton("Сменить пароль", "default", small=True)
        self.btn_change.clicked.connect(self._change)
        layout.addWidget(self.btn_change, 0, Qt.AlignLeft)

        self.status = QLabel("")
        self.status.setObjectName("SuccessText")
        layout.addWidget(self.status)

        # --- тема ---
        layout.addSpacing(8)
        layout.addWidget(self._sep())
        layout.addWidget(self._section("ТЕМА"))
        theme_row = QHBoxLayout()
        self.btn_light = BrutalButton("Светлая", "minimal", small=True)
        self.btn_dark = BrutalButton("Тёмная", "minimal", small=True)
        self.btn_light.clicked.connect(lambda: self._set_theme("light"))
        self.btn_dark.clicked.connect(lambda: self._set_theme("dark"))
        theme_row.addWidget(self.btn_light)
        theme_row.addWidget(self.btn_dark)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        # --- секция «Центр» (только если режим сконфигурирован) ---------------
        if self._c.central_available():
            layout.addSpacing(8)
            layout.addWidget(self._sep())
            layout.addWidget(self._section("АККАУНТ «ЦЕНТР»"))

            self.wipe_on_logout = BrutalCheckBox("Стирать историю «Центра» при выходе")
            self.wipe_on_logout.setChecked(self._c.central_wipe_on_logout())
            self.wipe_on_logout.toggled.connect(self._c.set_central_wipe_on_logout)
            layout.addWidget(self.wipe_on_logout)

            self.btn_logout = BrutalButton(
                "Выйти из аккаунта", "minimal", small=True, danger=True
            )
            self.btn_logout.setEnabled(self._c.central_session() is not None)
            self.btn_logout.clicked.connect(self._logout)
            layout.addWidget(self.btn_logout, 0, Qt.AlignLeft)

        layout.addSpacing(12)
        layout.addWidget(self._sep())
        done = BrutalButton("Готово", "primary", small=True)
        done.clicked.connect(self.accept)
        layout.addWidget(done, 0, Qt.AlignRight)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionLabel")
        return lbl

    def _sep(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("Sep")
        sep.setFrameShape(QFrame.HLine)
        return sep

    def _set_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if app is not None:
            theme.set_theme(app, mode)
            from mys_ui import prefs
            prefs.save_theme(mode)  # тема переживает перезапуск

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
