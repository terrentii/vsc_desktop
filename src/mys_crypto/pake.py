"""CPace — балансный PAKE на ristretto255 (крипто-ядро).

Из общей секретной фразы (точнее — производного от неё PRS) две стороны получают
равный сессионный ключ ``ISK`` и защиту от MITM, не раскрывая фразу серверу.
Чистые функции над байтами/точками: ни сокетов, ни I/O (граница CLAUDE.md —
крипто не знает о сети). Группа — аудированный ristretto255 из libsodium
(:mod:`mys_crypto._ristretto`); собственной математики группы здесь нет.

Ciphersuite в духе CPace-ristretto255 (CFRG draft): map-to-group через
``ristretto255_from_hash(SHA-512(...))``, обмен ``Y = y·G``, общий
``K = y·Y_peer``, ``ISK`` — хеш транскрипта. Точное байтовое кодирование
generator-строки (lv_cat/zero-pad из черновика) здесь упрощено до
length-prefixed конкатенации с фиксированными DSI-метками — это сохраняет
доменное разделение и самосогласованность сторон (см. план под-проекта №4); на
совместимость с внешними CPace-реализациями модуль не претендует.

Из ``ISK`` слой хендшейка (:mod:`mys_decentralized.handshake`) выводит корневой
ключ ratchet и стартовый DH — здесь этого нет (крипто без сети).
"""

import hashlib
from dataclasses import dataclass

from . import _ristretto

_DSI_GEN = b"MYS-CPace-ristretto255-gen"
_DSI_ISK = b"MYS-CPace-ristretto255-ISK"


def _lv(chunk: bytes) -> bytes:
    """Length-value: 2-байтовая длина (big-endian) ‖ данные — без неоднозначности
    конкатенации (доменное разделение полей транскрипта)."""
    if len(chunk) > 0xFFFF:
        raise ValueError("поле CPace длиннее 65535 байт")
    return len(chunk).to_bytes(2, "big") + chunk


@dataclass
class CPaceState:
    """Эфемерное состояние одной стороны между ``cpace_msg`` и ``cpace_finish``."""

    y: bytes      # секретный скаляр
    Y: bytes      # собственная публичная точка (= y·G)
    sid: bytes    # идентификатор сессии (входит в ISK)


def cpace_generator(prs: bytes, sid: bytes, ci: bytes = b"", ad: bytes = b"") -> bytes:
    """Map-to-group: PRS (+ контекст) → общая точка-генератор ristretto255.

    Обе стороны при равных входах получают одну и ту же точку; противник без
    знания PRS не может её вычислить.
    """
    gen_string = _DSI_GEN + _lv(prs) + _lv(sid) + _lv(ci) + _lv(ad)
    digest = hashlib.sha512(gen_string).digest()
    return _ristretto.from_hash(digest)


def cpace_msg(prs: bytes, sid: bytes, ci: bytes = b"", ad: bytes = b"") -> tuple[CPaceState, bytes]:
    """Сгенерировать эфемерный скаляр и публичное сообщение ``Y = y·G``.

    Возвращает ``(state, Y)``; ``Y`` уходит пиру, ``state`` — для ``cpace_finish``.
    """
    g = cpace_generator(prs, sid, ci, ad)
    y = _ristretto.scalar_random()
    big_y = _ristretto.scalarmult(y, g)
    return CPaceState(y=y, Y=big_y, sid=sid), big_y


def cpace_finish(state: CPaceState, peer_y: bytes) -> bytes:
    """Свести общий секрет с точкой пира и вывести 64-байтовый ``ISK``.

    ``K = y·Y_peer``; отказ (``RistrettoError``) при identity/невалидной точке
    пира. Порядок точек в транскрипте фиксирован лексикографически, чтобы обе
    стороны хешировали одинаково (CPace симметричен).
    """
    k = _ristretto.scalarmult(state.y, peer_y)  # бросит на identity/битой точке
    low, high = sorted((state.Y, peer_y))
    transcript = _DSI_ISK + _lv(state.sid) + _lv(low) + _lv(high) + _lv(k)
    return hashlib.sha512(transcript).digest()
