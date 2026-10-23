"""Настройки комнаты «Центра»: общее, аватарка, участники, диалог, приватность.

Разделы зависят от роли и режима (как веб-страница /room/<код>/settings). Сетевые
вызовы — в фоновом потоке: сервер бывает медленным, окно не должно замирать.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from mys_ui.widgets.avatar import avatar_pixmap
from mys_ui.widgets.brutal import BrutalButton, BrutalCheckBox, BrutalLineEdit
from mys_ui.windows.frameless import FramelessDialog

ERRORS = {
    "forbidden": "Нет прав на это действие.",
    "dialog": "В диалоге состав и открытость менять нельзя.",
    "not_dialog": "Доступно только в диалоге.",
    "not_eligible": "Диалог возможен только в комнате ровно на двух зарегистрированных.",
    "no_proposal": "Предложение уже неактуально.",
    "user_not_found": "Пользователь не найден.",
    "self": "Нельзя выбрать самого себя.",
    "creator": "Создатель не может покинуть комнату.",
    "bad_image": "Нужна картинка PNG, JPEG или WebP.",
    "too_large": "Картинка больше 5 МБ.",
    "rate_limited": "Слишком много приглашений за сутки.",
}


class _Done(QObject):
    done = Signal(object, object)  # (результат, исключение)


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("FieldLabel")
    return lbl


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("StatusMono")
    lbl.setWordWrap(True)
    return lbl


class RoomSettingsDialog(FramelessDialog):
    def __init__(self, parent, controller, conversation_id: int):
        super().__init__("Настройки комнаты", parent)
        self.setMinimumWidth(560)
        self._svc = controller.central()
        self._conv = conversation_id
        self._members: list[dict] = []
        self._me: dict = {}
        self._sig = _Done()
        self._sig.done.connect(self._on_done)
        self._content = QWidget()
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(10)
        self.body_layout.addWidget(self._content)
        self._error = QLabel()
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.hide()
        self.body_layout.addWidget(self._error)
        self._lay.addWidget(_hint("Загрузка…"))
        self._run(self._load)

    # -- фон ------------------------------------------------------------------

    def _load(self):
        meta = self._svc.room_call(self._conv, "get_room")
        if meta is None:
            return None
        return {"meta": meta, "me": self._svc.me(), "avatar": self._svc.avatar(self._conv)}

    def _run(self, fn):
        self._content.setEnabled(False)

        def work():
            try:
                self._sig.done.emit(fn(), None)
            except Exception as exc:  # сеть/сервер — показать текст, окно не закрывать
                self._sig.done.emit(None, exc)

        threading.Thread(target=work, daemon=True).start()

    def _op(self, op, *args):
        """Операция над комнатой, затем свежая загрузка (мета, участники, аватар)."""
        def fn():
            if self._svc.room_call(self._conv, op, *args) is None:
                return None  # вышли / комнату удалили
            return self._load()
        self._run(fn)

    def _on_done(self, res, err):
        self._content.setEnabled(True)
        if err is not None:
            self._error.setText(ERRORS.get(str(err), str(err)))
            self._error.show()
            return
        self._error.hide()
        if res is None:
            self.accept()  # комнаты у нас больше нет
            return
        self._me = res.get("me") or self._me
        self._members = res["meta"].get("member_list", self._members)
        self._build(res["meta"], res.get("avatar"))

    # -- разметка ---------------------------------------------------------------

    def _clear(self):
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def _row(self, *widgets) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        for w in widgets:
            h.addWidget(w, 1 if isinstance(w, BrutalLineEdit) else 0)
        h.addStretch()
        return box

    def _button(self, text, slot, variant="default", danger=False) -> BrutalButton:
        b = BrutalButton(text, variant, small=True, danger=danger)
        b.clicked.connect(slot)
        return b

    def _build(self, meta: dict, avatar: bytes | None) -> None:
        self._clear()
        login = self._me.get("login")
        dialog = bool(meta.get("is_dialog"))
        creator = meta.get("role") == "godfather"
        title = meta.get("title") or meta.get("name") or f"Комната {meta.get('code')}"

        head_avatar = QLabel()
        head_avatar.setPixmap(avatar_pixmap(avatar, title, 64))
        name = QLabel(title)
        name.setObjectName("ChatName")
        kind = _hint("ДИАЛОГ" if dialog else f"КОД {meta.get('code')}")
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(name)
        cl.addWidget(kind)
        self._lay.addWidget(self._row(head_avatar, col))

        proposed = meta.get("dialog_proposed_by")
        if proposed and not dialog:
            if proposed == login:
                self._lay.addWidget(_hint(f"Вы предложили {meta.get('peer')} перейти в диалог — ждём ответа."))
                self._lay.addWidget(self._row(self._button("Отозвать", lambda: self._op("dialog_action", "decline"))))
            else:
                what = "приглашает вас в диалог" if meta.get("role") == "invited" else "предлагает сделать комнату диалогом"
                self._lay.addWidget(_hint(f"{proposed} {what}."))
                self._lay.addWidget(self._row(
                    self._button("Принять", lambda: self._op("dialog_action", "accept"), "primary"),
                    self._button("Отклонить", lambda: self._op("dialog_action", "decline")),
                ))

        if dialog:
            self._lay.addWidget(_section("Моё название"))
            self._lay.addWidget(_hint("Видите только вы; пусто — логин собеседника."))
            own = BrutalLineEdit(meta.get("title") if meta.get("title") != meta.get("peer") else "")
            own.setPlaceholderText(meta.get("peer") or "")
            self._lay.addWidget(self._row(own, self._button("Сохранить", lambda: self._op("set_room_title", own.text().strip()), "primary")))
        elif creator and not meta.get("is_direct"):
            self._lay.addWidget(_section("Общее"))
            room_name = BrutalLineEdit(meta.get("name") or "")
            room_name.setPlaceholderText("Название (пусто — показывать код)")
            is_open = BrutalCheckBox("Открытая — войти может любой с кодом")
            is_open.setChecked(bool(meta.get("is_open")))
            self._lay.addWidget(room_name)
            self._lay.addWidget(is_open)
            self._lay.addWidget(self._row(self._button(
                "Сохранить", lambda: self._op("update_room", room_name.text().strip(), is_open.isChecked()), "primary")))

        if dialog or creator:
            self._lay.addWidget(_section("Моя аватарка диалога" if dialog else "Аватарка комнаты"))
            buttons = [self._button("Выбрать картинку", self._pick_avatar)]
            if meta.get("avatar_rev"):
                buttons.append(self._button("Убрать", lambda: self._op("delete_avatar")))
            self._lay.addWidget(self._row(*buttons))
            self._lay.addWidget(_hint("PNG, JPEG, WebP до 5 МБ; метаданные фото удаляются."))

        if not dialog and not meta.get("is_direct"):
            self._lay.addWidget(_section(f"Участники · {len(self._members)}"))
            for m in self._members:
                role = {"godfather": "прародитель", "invited": "приглашён"}.get(m.get("role"), "участник")
                label = QLabel(f"{m.get('login')}  ·  {role}")
                widgets = [label]
                if creator and m.get("login") != login:
                    widgets.append(self._button("Удалить", lambda _=False, who=m.get("login"): self._op("remove_member", who), danger=True))
                self._lay.addWidget(self._row(*widgets))
            if creator:
                add = BrutalLineEdit()
                add.setPlaceholderText("Добавить по логину")
                self._lay.addWidget(self._row(add, self._button("Добавить", lambda: self._op("add_member", add.text().strip()))))

        if not meta.get("is_direct"):
            self._lay.addWidget(_section("Диалог"))
            eligible = (len(self._members) == 2 and not proposed
                        and all(m.get("role") != "invited" for m in self._members))
            if dialog:
                self._lay.addWidget(_hint(f"Закрытая комната только для вас и {meta.get('peer')}: пузыри, «прочитано», «печатает», «в сети»."))
                self._lay.addWidget(self._row(self._button("Выключить диалог", lambda: self._op("dialog_action", "disable"))))
            elif eligible:
                self._lay.addWidget(_hint(f"В комнате двое — её можно сделать личным диалогом; {meta.get('peer')} должен согласиться."))
                self._lay.addWidget(self._row(self._button("Сделать диалогом", lambda: self._op("dialog_action", "propose"), "primary")))
            elif not proposed:
                self._lay.addWidget(_hint("Диалог возможен, когда в комнате ровно два зарегистрированных участника."))

            self._lay.addWidget(_section("Приватность (все диалоги)"))
            share_read = BrutalCheckBox("Показывать, что я прочитал")
            share_read.setChecked(bool(self._me.get("share_read", True)))
            share_online = BrutalCheckBox("Показывать, что я в сети")
            share_online.setChecked(bool(self._me.get("share_online", True)))
            self._lay.addWidget(share_read)
            self._lay.addWidget(share_online)
            self._lay.addWidget(self._row(self._button("Сохранить", lambda: self._save_privacy(share_read.isChecked(), share_online.isChecked()))))

        if not creator and not meta.get("is_direct"):
            self._lay.addWidget(self._row(self._button("Покинуть комнату", lambda: self._op("leave_room"), danger=True)))
        self.adjustSize()

    # -- действия ---------------------------------------------------------------

    def _pick_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Картинка", "", "Картинки (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read(5 * 1024 * 1024 + 1)
        self._op("put_avatar", data)

    def _save_privacy(self, share_read: bool, share_online: bool) -> None:
        def fn():
            self._svc.set_privacy(share_read=share_read, share_online=share_online)
            return self._load()
        self._run(fn)
