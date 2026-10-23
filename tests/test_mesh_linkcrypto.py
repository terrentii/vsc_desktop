import pytest

from mys_crypto import linkcrypto as L


def _pair():
    a_pk, a_sk = L.kx_keypair()
    b_pk, b_sk = L.kx_keypair()
    return L.kx_session_keys(a_pk, a_sk, b_pk), L.kx_session_keys(b_pk, b_sk, a_pk)


def test_kx_keys_match_crosswise():
    (a_rx, a_tx), (b_rx, b_tx) = _pair()
    assert a_tx == b_rx and a_rx == b_tx and a_tx != a_rx


def test_stream_roundtrip_and_replay_rejected():
    (_, tx), (rx, _) = _pair()
    push = L.Pusher(tx)
    pull = L.Puller(rx, push.header)
    c1, c2 = push.push(b"one"), push.push(b"")
    assert pull.pull(c1) == b"one"
    assert pull.pull(c2) == b""
    with pytest.raises(L.LinkCryptoError):
        pull.pull(c2)


def test_tampered_rejected():
    (_, tx), (rx, _) = _pair()
    push = L.Pusher(tx)
    pull = L.Puller(rx, push.header)
    c = bytearray(push.push(b"secret"))
    c[-1] ^= 1
    with pytest.raises(L.LinkCryptoError):
        pull.pull(bytes(c))


def test_same_or_bad_key_rejected():
    pk, sk = L.kx_keypair()
    with pytest.raises(L.LinkCryptoError):
        L.kx_session_keys(pk, sk, pk)
    with pytest.raises(L.LinkCryptoError):
        L.kx_session_keys(pk, sk, b"short")
