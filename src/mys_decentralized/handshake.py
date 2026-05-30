"""Хендшейк: CPace поверх готового транспорта → ``sk`` + инициализированный ratchet.

Склейка крипто+сеть (граница CLAUDE.md): получает уже установленный транспорт
непрозрачных кадров и `prs` от вышестоящего слоя, прогоняет балансный CPace
(:mod:`mys_crypto.pake`), подтверждает ключ и выводит вход для Double Ratchet
ядра. Закрывает follow-up «вход для ratchet»: `sk` и стартовый DH-ключ Боба
рождаются из общего `ISK`, а не задаются снаружи.

Поток (§6 спеки):
  1. обмен ``PAKE{Y}``;
  2. ``ISK = cpace_finish(...)`` (отказ на identity/битой точке пира);
  3. обмен ``CONFIRM{mac}``, ``mac = HMAC(ISK, "mys-confirm" || sort(Ya,Yb))`` —
     несовпадение ⇒ :class:`PAKEError` (неверная фраза или MITM);
  4. ``sk``/``bob_dh_seed`` из ``ISK`` (HKDF, независимые info); init ratchet по роли.

Атакующий без знания `prs` не может вычислить общую точку-генератор, значит не
получит равный ``ISK`` и не подделает ``CONFIRM`` — худший случай сводится к
обычному CPace.
"""

import hashlib
import hmac
from dataclasses import dataclass

from mys_crypto import pake
from mys_crypto.primitives import hkdf, x25519_keypair_from_seed
from mys_crypto.ratchet import RatchetState, ratchet_init_alice, ratchet_init_bob

from .errors import PAKEError
from .protocol import Confirm, Pake, Role, decode_message, encode_message
from .transport import Transport

_CONFIRM_LABEL = b"mys-confirm"


@dataclass
class HandshakeResult:
    """Итог хендшейка: вход для сессии (ratchet уже инициализирован по роли)."""

    sk: bytes
    ratchet_state: RatchetState
    isk: bytes  # для key-confirmation/диагностики; в сеть не уходит


def _derive_sid(prs: bytes) -> bytes:
    """Идентификатор сессии CPace, детерминированно из `prs` (обе стороны равны).

    Эфемерность хендшейка обеспечивает случайный скаляр `y` в `cpace_msg`, а не
    `sid`; здесь `sid` лишь доменно привязывает транскрипт к этой паре фраз."""
    return hashlib.blake2b(prs, digest_size=16, person=b"mys-cpace-sid").digest()


def _confirm_mac(isk: bytes, my_y: bytes, peer_y: bytes) -> bytes:
    low, high = sorted((my_y, peer_y))
    return hmac.new(isk, _CONFIRM_LABEL + low + high, hashlib.sha256).digest()


async def _recv_message(transport: Transport):
    msg, _consumed = decode_message(await transport.recv())
    return msg


async def handshake(transport: Transport, prs: bytes, role: Role) -> HandshakeResult:
    """Прогнать CPace+confirm поверх `transport` и вернуть вход для сессии."""
    sid = _derive_sid(prs)

    state, my_y = pake.cpace_msg(prs, sid)
    await transport.send(encode_message(Pake(y=my_y)))

    peer_msg = await _recv_message(transport)
    if not isinstance(peer_msg, Pake):
        raise PAKEError("ожидался PAKE на шаге обмена точками")
    isk = pake.cpace_finish(state, peer_msg.y)  # бросит на identity/битой точке

    my_mac = _confirm_mac(isk, my_y, peer_msg.y)
    await transport.send(encode_message(Confirm(mac=my_mac)))

    confirm_msg = await _recv_message(transport)
    if not isinstance(confirm_msg, Confirm):
        raise PAKEError("ожидался CONFIRM на шаге подтверждения ключа")
    if not hmac.compare_digest(confirm_msg.mac, my_mac):
        raise PAKEError("key-confirmation не сошёлся: неверная фраза или MITM")

    sk = hkdf(isk, 32, salt=b"", info=b"mys-ratchet-root")
    bob_dh_seed = hkdf(isk, 32, salt=b"", info=b"mys-ratchet-bob-dh")
    bob_dh_keypair = x25519_keypair_from_seed(bob_dh_seed)

    if role == Role.INITIATOR:
        ratchet_state = ratchet_init_alice(sk, bob_dh_keypair[1])
    else:
        ratchet_state = ratchet_init_bob(sk, bob_dh_keypair)

    return HandshakeResult(sk=sk, ratchet_state=ratchet_state, isk=isk)
