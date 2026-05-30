"""Хендшейк: CPace поверх транспорта → согласованные sk + init ratchet.

Закрывает follow-up крипто-ядра «вход для ratchet»: sk и стартовый DH приходят
из PAKE, а не задаются извне.
"""

import asyncio

import pytest

from mys_crypto import envelope, pake
from mys_crypto.ratchet import ratchet_decrypt, ratchet_encrypt
from mys_decentralized.errors import PAKEError
from mys_decentralized.handshake import handshake
from mys_decentralized.protocol import Confirm, Pake, Role, encode_message
from mys_decentralized.transport import InMemoryTransport


async def test_handshake_agrees_and_ratchet_works():
    alice_t, bob_t = InMemoryTransport.connected_pair()
    prs = b"shared-prs-from-phrase"

    a_res, b_res = await asyncio.gather(
        handshake(alice_t, prs, Role.INITIATOR),
        handshake(bob_t, prs, Role.RESPONDER),
    )

    # Обе стороны вывели один и тот же корневой ключ и ISK.
    assert a_res.sk == b_res.sk
    assert a_res.isk == b_res.isk

    # Первый seal/open через инициализированный ratchet проходит:
    # Alice (initiator) шифрует, Bob (responder) расшифровывает.
    tk = envelope.derive_transform_key(a_res.sk)
    sealed = envelope.seal(a_res.ratchet_state, tk, b"hi bob")
    assert envelope.open_(b_res.ratchet_state, tk, sealed) == b"hi bob"

    # И обратно.
    sealed2 = envelope.seal(b_res.ratchet_state, tk, b"hi alice")
    assert envelope.open_(a_res.ratchet_state, tk, sealed2) == b"hi alice"


async def test_handshake_different_phrase_fails_confirmation():
    alice_t, bob_t = InMemoryTransport.connected_pair()

    with pytest.raises(PAKEError):
        await asyncio.gather(
            handshake(alice_t, b"phrase-A", Role.INITIATOR),
            handshake(bob_t, b"phrase-B", Role.RESPONDER),
        )


async def test_handshake_mitm_forged_confirm_rejected():
    """Атакующий без знания prs не может подделать key-confirmation."""
    honest_t, attacker_t = InMemoryTransport.connected_pair()
    prs = b"only-honest-knows-this"

    async def attacker() -> None:
        await attacker_t.recv()  # честный PAKE
        # Валидная по форме точка ristretto, но не из настоящего prs.
        _state, bogus_y = pake.cpace_msg(b"guess", b"sid")
        await attacker_t.send(encode_message(Pake(y=bogus_y)))
        await attacker_t.recv()  # честный CONFIRM
        await attacker_t.send(encode_message(Confirm(mac=b"\x00" * 32)))

    with pytest.raises(PAKEError):
        await asyncio.gather(
            handshake(honest_t, prs, Role.INITIATOR),
            attacker(),
        )
