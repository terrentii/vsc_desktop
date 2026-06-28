from mys_ui import theme
from mys_ui.widgets.chat_view import ChatView, MessageRow
from mys_ui.widgets.code_block import CodeBlock
from mys_ui.widgets.media_view import MediaView


def _msg(direction, body, **extra):
    base = {
        "direction": direction, "body": body.encode("utf-8"),
        "author": None, "created_ts": None, "sent_at": None, "received_at": None,
        "media": None,
    }
    base.update(extra)
    return base


def test_own_message_uses_accent_name(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("out", "привет")], peer_label="bob")
    row = cv.item(0)
    assert isinstance(row, MessageRow)
    assert row.author == "я"
    assert row.author_color == theme.tokens()["accent"]


def test_incoming_message_uses_author_name(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "йо", author="alice")], peer_label="bob")
    row = cv.item(0)
    assert row.author == "alice"
    assert row.author_color == theme.tokens()["text"]


def test_incoming_without_author_falls_back_to_peer(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "йо")], peer_label="bob")
    assert cv.item(0).author == "bob"


def test_code_segment_renders_code_block(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "до\n```\ncode\n```", author="a")], peer_label="b")
    row = cv.item(0)
    assert len(row.findChildren(CodeBlock)) == 1


def test_media_renders_media_view(qtbot, tmp_path):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "файл", author="a", media="doc.pdf")], peer_label="b")
    row = cv.item(0)
    assert len(row.findChildren(MediaView)) == 1


def test_time_prefers_created_ts(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages(
        [_msg("in", "йо", author="a", created_ts=1719489600.0, received_at=1.0)],
        peer_label="b",
    )
    row = cv.item(0)
    assert row.when != ""
    assert not row.when.startswith("00:00")


def test_item_text_holds_raw_body(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "привет", author="a")], peer_label="b")
    assert cv.count() == 1
    assert "привет" in cv.item(0).text()


def test_body_and_author_not_rendered_as_html(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages(
        [_msg("in", "<b>злой</b>", author="<i>peer</i>")], peer_label="b"
    )
    row = cv.item(0)
    labels = row.findChildren(QLabel)
    # все текстовые лейблы (имя, тело) — в режиме PlainText
    plains = [lb for lb in labels if lb.textFormat() == Qt.PlainText]
    texts = [lb.text() for lb in plains]
    assert "<b>злой</b>" in texts
    assert "<i>peer</i>" in texts
