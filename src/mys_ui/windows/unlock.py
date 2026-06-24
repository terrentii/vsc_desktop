"""Окно входа: создание или разблокировка vault (карточка в стиле дизайна)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mys_storage import VaultLocked, WrongPassword

from mys_ui import theme


class UnlockWindow(QWidget):
    unlocked = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._creating = not controller.vault_exists()

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)

        card = QWidget()
        card.setObjectName("VaultCard")
        card.setFixedWidth(420)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 30, 32, 30)
        layout.setSpacing(8)

        brand = QLabel("МЫС")
        brand.setObjectName("BrandMark")
        brand.setFont(theme.display_font(34))
        brand.setAlignment(Qt.AlignCenter)
        self.title = QLabel(
            "СОЗДАНИЕ ХРАНИЛИЩА" if self._creating else "РАЗБЛОКИРОВКА VAULT"
        )
        self.title.setObjectName("VaultTitle")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(brand)
        layout.addWidget(self.title)
        layout.addSpacing(14)

        layout.addWidget(self._label("МАСТЕР-ПАРОЛЬ"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("••••••••")
        layout.addWidget(self.password)

        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        self.confirm.setPlaceholderText("••••••••")
        if self._creating:
            layout.addSpacing(6)
            layout.addWidget(self._label("ПОВТОРИТЕ ПАРОЛЬ"))
            layout.addWidget(self.confirm)

        layout.addSpacing(14)
        layout.addWidget(self._warn_box())
        layout.addSpacing(6)

        self.error = QLabel("")
        self.error.setObjectName("ErrorText")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.submit = QPushButton("СОЗДАТЬ" if self._creating else "РАЗБЛОКИРОВАТЬ")
        self.submit.setObjectName("PrimaryBtn")
        self.submit.setCursor(Qt.PointingHandCursor)
        self.submit.clicked.connect(self._on_submit)
        self.password.returnPressed.connect(self._on_submit)
        self.confirm.returnPressed.connect(self._on_submit)
        layout.addWidget(self.submit)

        outer.addWidget(card)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _warn_box(self) -> QWidget:
        box = QWidget()
        box.setObjectName("WarnBox")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        icon = QLabel("⚠")
        icon.setStyleSheet(f"color: {theme.tokens()['warning']}; background: transparent;")
        icon.setAlignment(Qt.AlignTop)
        text = QLabel(
            "Пароль невозможно восстановить. Хранилище зашифровано на устройстве — "
            "забыли пароль, потеряли все сообщения."
        )
        text.setObjectName("WarnBoxText")
        text.setWordWrap(True)
        lay.addWidget(icon)
        lay.addSpacing(8)
        lay.addWidget(text, 1)
        return box

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
