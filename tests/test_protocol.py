"""Тесты wire-протокола: деривация room_id/prs, фрейминг, сериализация сообщений."""

import pytest

from mys_decentralized import protocol as p
from mys_decentralized.errors import TransportError


# --- деривация room_id / prs -------------------------------------------------

def test_derive_room_params_deterministic():
    a = p.derive_room_params("общая секретная фраза")
    b = p.derive_room_params("общая секретная фраза")
    assert a == b
    room_id, prs = a
    assert len(room_id) == 32 and len(prs) == 32


def test_room_id_and_prs_are_independent():
    room_id, prs = p.derive_room_params("phrase")
    assert room_id != prs


def test_phrase_normalization_nfkc_and_strip():
    # NFKC схлопывает совместимые формы; обрамляющие пробелы убираются.
    base = p.derive_room_params("café")
    assert p.derive_room_params("  café  ") == base
    assert p.derive_room_params("café") == base  # 'e' + комбинирующий акут


def test_different_phrases_differ():
    assert p.derive_room_params("alpha") != p.derive_room_params("beta")


# --- фрейминг ----------------------------------------------------------------

def test_frame_round_trip():
    frame = p.encode_frame(p.MsgType.DATA, b"opaque-payload", flags=3)
    mtype, flags, payload, consumed = p.decode_frame(frame)
    assert mtype == p.MsgType.DATA
    assert flags == 3
    assert payload == b"opaque-payload"
    assert consumed == len(frame)


def test_decode_frame_leaves_trailing_bytes():
    frame = p.encode_frame(p.MsgType.RELAY, b"abc")
    buf = frame + b"next-frame-start"
    mtype, _flags, payload, consumed = p.decode_frame(buf)
    assert mtype == p.MsgType.RELAY and payload == b"abc"
    assert buf[consumed:] == b"next-frame-start"


def test_decode_frame_rejects_truncated_header():
    with pytest.raises(TransportError):
        p.decode_frame(b"\x01\x00\x00")  # короче 6-байтового заголовка


def test_decode_frame_rejects_incomplete_payload():
    frame = p.encode_frame(p.MsgType.DATA, b"12345")
    with pytest.raises(TransportError):
        p.decode_frame(frame[:-2])  # length обещает больше, чем есть


# --- сериализация сообщений --------------------------------------------------

def test_hello_round_trip():
    msg = p.Hello(room_id=b"r" * 32, candidates=[("127.0.0.1", 5000), ("10.0.0.2", 6001)])
    frame = p.encode_message(msg)
    out, consumed = p.decode_message(frame)
    assert out == msg and consumed == len(frame)


def test_pair_round_trip():
    msg = p.Pair(role=p.Role.RESPONDER, peer_candidates=[("192.168.1.5", 7000)])
    out, _ = p.decode_message(p.encode_message(msg))
    assert out == msg


def test_pake_round_trip():
    msg = p.Pake(y=b"Y" * 32, ad=b"context")
    out, _ = p.decode_message(p.encode_message(msg))
    assert out == msg


def test_confirm_round_trip():
    msg = p.Confirm(mac=b"m" * 32)
    out, _ = p.decode_message(p.encode_message(msg))
    assert out == msg


def test_data_round_trip():
    msg = p.Data(sealed=b"\x00\x01\x02sealed-blob")
    out, _ = p.decode_message(p.encode_message(msg))
    assert out == msg


def test_relay_round_trip():
    msg = p.Relay(payload=b"forwarded-bytes")
    out, _ = p.decode_message(p.encode_message(msg))
    assert out == msg


def test_punch_round_trip():
    out, _ = p.decode_message(p.encode_message(p.Punch()))
    assert isinstance(out, p.Punch)
    ack, _ = p.decode_message(p.encode_message(p.PunchAck()))
    assert isinstance(ack, p.PunchAck)


def test_decode_message_unknown_type_rejected():
    raw = bytes([0xFE, 0, 0, 0, 0, 0])  # тип 0xFE не определён
    with pytest.raises(TransportError):
        p.decode_message(raw)
