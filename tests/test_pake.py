"""Тесты CPace-ristretto255 (балансный PAKE) в крипто-ядре.

Точные байтовые тест-векторы CFRG требуют буквального lv_cat/zero-pad кодирования
generator-строки; по плану под-проекта №4 при расхождении формата приоритет —
самосогласованность сторон с явной фиксацией меток. Поэтому тесты проверяют
структурные свойства CPace: детерминизм генератора, равный ISK у сторон при равной
фразе, расхождение при разной фразе, отказ на identity/битой точке.
"""

import pytest

from mys_crypto import pake
from mys_crypto._ristretto import RistrettoError, is_valid_point


PRS = b"correct horse battery staple"
SID = b"room-12345678"


def test_generator_deterministic_and_valid_point():
    g1 = pake.cpace_generator(PRS, SID)
    g2 = pake.cpace_generator(PRS, SID)
    assert g1 == g2
    assert len(g1) == 32
    assert is_valid_point(g1)


def test_generator_depends_on_inputs():
    base = pake.cpace_generator(PRS, SID)
    assert pake.cpace_generator(b"other phrase", SID) != base
    assert pake.cpace_generator(PRS, b"other-sid") != base
    assert pake.cpace_generator(PRS, SID, ci=b"x") != base
    assert pake.cpace_generator(PRS, SID, ad=b"x") != base


def test_both_sides_agree_on_isk():
    state_a, ya = pake.cpace_msg(PRS, SID)
    state_b, yb = pake.cpace_msg(PRS, SID)
    assert ya != yb  # независимые эфемерные скаляры
    isk_a = pake.cpace_finish(state_a, yb)
    isk_b = pake.cpace_finish(state_b, ya)
    assert isk_a == isk_b
    assert len(isk_a) == 64


def test_transcript_symmetric_regardless_of_message_order():
    # ISK не должен зависеть от того, кто «первый» — порядок Y фиксирован
    # лексикографически внутри cpace_finish.
    state_a, ya = pake.cpace_msg(PRS, SID)
    state_b, yb = pake.cpace_msg(PRS, SID)
    assert pake.cpace_finish(state_a, yb) == pake.cpace_finish(state_b, ya)


def test_different_phrase_yields_different_isk():
    state_a, ya = pake.cpace_msg(PRS, SID)
    state_b, yb = pake.cpace_msg(b"wrong phrase", SID)
    isk_a = pake.cpace_finish(state_a, yb)
    isk_b = pake.cpace_finish(state_b, ya)
    assert isk_a != isk_b


def test_finish_rejects_identity_point():
    state, _ = pake.cpace_msg(PRS, SID)
    identity = bytes(32)  # каноническая identity ristretto255
    with pytest.raises(RistrettoError):
        pake.cpace_finish(state, identity)


def test_finish_rejects_malformed_point():
    state, _ = pake.cpace_msg(PRS, SID)
    with pytest.raises(RistrettoError):
        pake.cpace_finish(state, b"\xff" * 32)
