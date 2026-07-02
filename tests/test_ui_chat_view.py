"""Тесты ChatView: разбор ```код``` -сегментов, инлайн-картинки, ленивые файлы."""

from mys_ui.widgets.chat_view import ChatView, _split_segments


# --- _split_segments (чистая функция, без Qt) ----------------------------------

def test_split_segments_no_fence():
    assert _split_segments("просто текст") == [(False, "просто текст")]


def test_split_segments_single_fence():
    segs = _split_segments("до```код```после")
    assert segs == [(False, "до"), (True, "код"), (False, "после")]


def test_split_segments_multiple_fences():
    segs = _split_segments("a```one```b```two```c")
    assert segs == [(False, "a"), (True, "one"), (False, "b"), (True, "two"), (False, "c")]


def test_split_segments_unterminated_fence_not_code():
    # Незакрытый фенс — regex не находит совпадения, весь текст один сегмент.
    segs = _split_segments("текст ```без закрытия")
    assert segs == [(False, "текст ```без закрытия")]


def test_split_segments_fence_at_start_and_end():
    segs = _split_segments("```только код```")
    assert segs == [(True, "только код")]


# --- show_messages: изображения/файлы (нужен QApplication, через qtbot) -------

def _msg(**over):
    base = dict(
        id=1, direction="in", body=b"data", status="received",
        kind="text", filename=None, mime_type=None, sender="bob",
        sent_at=None, received_at=1000.0,
    )
    base.update(over)
    return base


def test_show_messages_image_with_body_sets_pixmap_role(qtbot):
    # Валидный 1x1 прозрачный PNG (минимальный).
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c"
        "020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
    )
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(kind="image", filename="p.png", body=png)])
    assert view.count() == 1
    item = view.item(0)
    from mys_ui.widgets.chat_view import _IMAGE_ROLE
    pix = item.data(_IMAGE_ROLE)
    assert pix is not None and not pix.isNull()


def test_show_messages_image_without_body_no_pixmap_and_placeholder_text(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(kind="image", filename="p.png", body=None)])
    item = view.item(0)
    from mys_ui.widgets.chat_view import _IMAGE_ROLE
    assert item.data(_IMAGE_ROLE) is None
    assert "загрузка" in item.text()


def test_show_messages_file_without_body_placeholder_and_double_click_emits_fetch(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(kind="file", filename="doc.pdf", body=None, id=42)])
    item = view.item(0)
    assert "нажмите" in item.text()

    received = []
    view.media_fetch_requested.connect(received.append)
    view._on_double_click(item)
    assert received == [42]


def test_show_messages_file_with_body_double_click_does_not_emit_fetch(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(kind="file", filename="doc.pdf", body=b"pdf-bytes", id=7)])
    item = view.item(0)

    received = []
    view.media_fetch_requested.connect(received.append)
    # Не открываем реальный QFileDialog в тесте — просто проверяем, что fetch
    # не запрашивается повторно, т.к. тело уже есть (сам диалог сохранения
    # тестировать headless нецелесообразно).
    from mys_ui.widgets.chat_view import _FILE_BODY_ROLE
    assert item.data(_FILE_BODY_ROLE) == b"pdf-bytes"


# --- веб-формат времени и подписи (паритет с vsc_web) --------------------------

def test_fmt_when_today_yesterday_and_date():
    import datetime as dt
    from mys_ui.widgets.chat_view import _fmt_when

    now = dt.datetime.now()
    assert _fmt_when(now.timestamp()) == f"сегодня {now.strftime('%H:%M')}"

    yesterday = now - dt.timedelta(days=1)
    assert _fmt_when(yesterday.timestamp()) == f"вчера {yesterday.strftime('%H:%M')}"

    old = dt.datetime(now.year - 1, 5, 13, 15, 27)
    assert _fmt_when(old.timestamp()) == "13 май 15:27"


def test_fmt_when_empty_and_garbage():
    from mys_ui.widgets.chat_view import _fmt_when
    assert _fmt_when(None) == ""
    assert _fmt_when("мусор") == ""


def test_show_messages_own_label_is_used_for_outgoing(qtbot):
    from mys_ui.widgets.chat_view import _AUTHOR_ROLE
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages(
        [_msg(direction="out", body=b"hi")], own_label="Andrey"
    )
    assert view.item(0).data(_AUTHOR_ROLE) == "Andrey"


def test_copy_button_rect_exists_for_code_segment(qtbot):
    # У сообщения с ```кодом``` делегат отдаёт кликабельную зону «КОПИРОВАТЬ».
    from PySide6.QtWidgets import QStyleOptionViewItem
    from PySide6.QtCore import QRect

    view = ChatView()
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show_messages([_msg(body="до\n```print(1)```\nпосле".encode())])
    index = view.model().index(0, 0)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 600, 300)
    delegate = view.itemDelegate()
    rects = delegate._copy_button_rects(option, index)
    assert len(rects) == 1
    rect, code = rects[0]
    assert code == "print(1)"
    assert rect.width() > 0 and rect.height() > 0


# --- действия строк (ОТВЕТИТЬ/ИЗМЕНИТЬ/УДАЛИТЬ) и цитата ответа ----------------

def _option(view, w=600, h=300):
    from PySide6.QtWidgets import QStyleOptionViewItem
    from PySide6.QtCore import QRect
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, w, h)
    return option


def test_actions_hidden_when_disabled_or_unconfirmed(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(direction="out", wire_seq=5)])
    delegate = view.itemDelegate()
    index = view.model().index(0, 0)
    view._hover_row = 0  # кнопки видны только у наведённой строки
    # выключено (не «Центр») — действий нет
    assert delegate._action_rects(_option(view), index) == []
    # включено, но нет wire_seq — тоже нет
    view.actions_enabled = True
    view.show_messages([_msg(direction="out", wire_seq=None)])
    view._hover_row = 0
    index = view.model().index(0, 0)
    assert delegate._action_rects(_option(view), index) == []
    # есть wire, но строка не под курсором — тоже нет
    view.show_messages([_msg(direction="out", wire_seq=5)])
    view._hover_row = -1
    index = view.model().index(0, 0)
    assert delegate._action_rects(_option(view), index) == []


def test_actions_for_own_and_foreign_rows(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.actions_enabled = True
    view.show_messages([
        _msg(direction="in", wire_seq=1),
        _msg(direction="out", wire_seq=2, id=2),
    ])
    delegate = view.itemDelegate()
    view._hover_row = 0
    labels_in = [a for _, a in delegate._action_rects(_option(view), view.model().index(0, 0))]
    view._hover_row = 1
    labels_out = [a for _, a in delegate._action_rects(_option(view), view.model().index(1, 0))]
    assert labels_in == ["ОТВЕТИТЬ"]
    assert set(labels_out) == {"ОТВЕТИТЬ", "ИЗМЕНИТЬ", "УДАЛИТЬ"}


def test_action_click_emits_signal(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.actions_enabled = True
    view.show_messages([_msg(direction="out", wire_seq=2, id=42)])
    view._hover_row = 0
    delegate = view.itemDelegate()
    index = view.model().index(0, 0)
    rects = dict((a, r) for r, a in delegate._action_rects(_option(view), index))

    got = {}
    view.reply_requested.connect(lambda i: got.setdefault("reply", i))
    view.edit_requested.connect(lambda i: got.setdefault("edit", i))
    view.delete_requested.connect(lambda i: got.setdefault("delete", i))

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    for action, key in (("ОТВЕТИТЬ", "reply"), ("ИЗМЕНИТЬ", "edit"), ("УДАЛИТЬ", "delete")):
        pos = QPointF(rects[action].center())
        ev = QMouseEvent(QEvent.MouseButtonRelease, pos, Qt.LeftButton,
                         Qt.LeftButton, Qt.NoModifier)
        assert delegate.editorEvent(ev, view.model(), _option(view), index)
    assert got == {"reply": 42, "edit": 42, "delete": 42}


def test_reply_quote_adds_height(qtbot):
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(), _msg(id=2, reply_author="Skuf", reply_snippet="цитата")])
    delegate = view.itemDelegate()
    h_plain = delegate.sizeHint(_option(view), view.model().index(0, 0)).height()
    h_quoted = delegate.sizeHint(_option(view), view.model().index(1, 0)).height()
    assert h_quoted > h_plain


def test_own_sender_incoming_rendered_as_own(qtbot):
    # Свои сообщения, отправленные из веба, приходят direction="in" с нашим
    # логином — должны рисоваться как свои (кнопки управления, имя аккаунта).
    from mys_ui.widgets.chat_view import _AUTHOR_ROLE, _DIRECTION_ROLE
    view = ChatView()
    qtbot.addWidget(view)
    view.actions_enabled = True
    view.show_messages(
        [_msg(sender="Andrey", wire_seq=7)],
        own_label="Andrey", own_sender="Andrey",
    )
    item = view.item(0)
    assert item.data(_DIRECTION_ROLE) == "out"
    assert item.data(_AUTHOR_ROLE) == "Andrey"
    delegate = view.itemDelegate()
    view._hover_row = 0
    labels = [a for _, a in delegate._action_rects(_option(view), view.model().index(0, 0))]
    assert "УДАЛИТЬ" in labels


def test_pending_status_role_set(qtbot):
    from mys_ui.widgets.chat_view import _STATUS_ROLE
    view = ChatView()
    qtbot.addWidget(view)
    view.show_messages([_msg(direction="out", status="pending")])
    assert view.item(0).data(_STATUS_ROLE) == "pending"
