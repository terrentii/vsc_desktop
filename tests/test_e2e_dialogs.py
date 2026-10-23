"""E2E: диалоги «Центра» против живого vsc_web — приглашение, принятие, мета,
«печатает», «прочитано», своё название и аватарка (vsc_web/dialogs.py)."""

from __future__ import annotations

import io
import uuid

import pytest

from mys_centralized.service import CentralizedService
from mys_storage import create_vault
from tests.test_e2e_centralized import FAST, _wait, live_vsc_web  # noqa: F401 — фикстура

pytestmark = pytest.mark.e2e_server


def _service(tmp_path, name, events):
    vault = create_vault(str(tmp_path / f"{name}.db"), f"pw-{name}".encode(), params=FAST)
    svc = CentralizedService(
        vault, on_room_event=lambda conv, kind, data: events.append((conv, kind, data)),
        room_poll_interval=0,
    )
    svc.start()
    return svc, vault


def _png() -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    img = QImage(40, 30, QImage.Format_RGB32)
    img.fill(QColor("#4d7bff"))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_dialog_lifecycle(live_vsc_web, tmp_path):
    ev_a, ev_b = [], []
    a, va = _service(tmp_path, "a", ev_a)
    b, vb = _service(tmp_path, "b", ev_b)
    ua, ub = f"a_{uuid.uuid4().hex[:8]}", f"b_{uuid.uuid4().hex[:8]}"
    try:
        a.login(live_vsc_web.url, ua, "pw-secret-1", register=True)
        b.login(live_vsc_web.url, ub, "pw-secret-1", register=True)
        _wait(lambda: b._ws is not None and b._ws._ws is not None, timeout=30)

        conv_a = a.invite(ub)
        meta = a.room_meta(conv_a)
        assert meta["pending_invite"] and meta["peer"] == ub and not meta["is_dialog"]

        # приглашение приходит живьём (room_updated по /ws)
        def invited():
            return next((c for c, m in b._sync.room_meta.items() if m.get("role") == "invited"), None)
        _wait(lambda: invited() is not None, timeout=20)
        conv_b = invited()
        assert b.room_call(conv_b, "dialog_action", "accept")["is_dialog"]
        _wait(lambda: (a.room_meta(conv_a) or {}).get("is_dialog"), timeout=20)

        # «печатает…»
        _wait(lambda: a._ws is not None and a._ws._ws is not None, timeout=30)
        b.typing(conv_b)
        _wait(lambda: any(c == conv_a and k == "typing" for c, k, _ in ev_a), timeout=20)

        # «прочитано»: a читает сообщение b — b видит peer_read
        b.send_message(conv_b, "привет")
        _wait(lambda: any(m["wire_seq"] for m in va.messages.list(conv_a)), timeout=20)
        wire = max(m["wire_seq"] for m in va.messages.list(conv_a) if m["wire_seq"])
        a.mark_read(conv_a, wire)
        _wait(lambda: (b.room_meta(conv_b) or {}).get("peer_read") == wire, timeout=20)

        # своё название и аватарка — только у себя
        assert a.room_call(conv_a, "set_room_title", "Друг")["title"] == "Друг"
        assert a.room_call(conv_a, "put_avatar", _png())["avatar_rev"] == 1
        assert a.avatar(conv_a)[:8] == b"\x89PNG\r\n\x1a\n"
        assert b.room_call(conv_b, "get_room")["avatar_rev"] == 0

        # выход собеседника выключает диалог; у вышедшего беседы больше нет
        assert b.room_call(conv_b, "leave_room") is None
        assert vb.conversations.get(conv_b) is None
        _wait(lambda: not (a.room_meta(conv_a) or {}).get("is_dialog", True), timeout=20)
    finally:
        a.stop()
        b.stop()
