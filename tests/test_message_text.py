from mys_ui.widgets.message_text import split_segments


def test_plain_text_single_segment():
    assert split_segments("привет мир") == [("text", "привет мир")]


def test_mixed_text_and_code():
    body = "до\n```\nx = 1\n```\nпосле"
    assert split_segments(body) == [
        ("text", "до\n"),
        ("code", "x = 1"),
        ("text", "\nпосле"),
    ]


def test_unterminated_fence_stays_text():
    assert split_segments("a```b") == [("text", "a```b")]


def test_empty_input():
    assert split_segments("") == [("text", "")]


def test_only_code():
    assert split_segments("```\ncode\n```") == [("code", "code")]
