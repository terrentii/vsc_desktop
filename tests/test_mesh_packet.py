import pytest

from mys_mesh import packet as P
from mys_mesh.tags import hour_of, tag_for_hour, tag_key

ID, TAG, N1, N2 = bytes(range(16)), bytes(range(32)), b"\x01" * 16, b"\x02" * 16


@pytest.mark.parametrize("p", [
    P.Packet(P.RREQ, ID, ttl=8, hops=3, tag=TAG, nonce=N1),
    P.Packet(P.RREP, ID, hops=1, route_id=N2, nonce=N1),
    P.Packet(P.DATA, ID, payload=b"mys"),
    P.Packet(P.DATA, ID),
    P.Packet(P.RERR, ID),
])
def test_roundtrip(p):
    assert P.decode(P.encode(p)) == p


@pytest.mark.parametrize("raw", [
    b"",
    bytes([2, P.RERR, 0, 0]) + ID,                       # версия
    bytes([1, 9, 0, 0]) + ID,                            # тип
    bytes([1, P.RREQ, 8, 0]) + ID + TAG,                 # короткий RREQ
    bytes([1, P.RREQ, 0, 0]) + ID + TAG + N1,            # ttl 0
    bytes([1, P.RREQ, 9, 0]) + ID + TAG + N1,            # ttl > max
    bytes([1, P.RREP, 0, 0]) + ID + N1,                  # короткий RREP
    bytes([1, P.RERR, 0, 0]) + ID + b"x",                # RERR с телом
    bytes([1, P.DATA, 1, 0]) + ID,                       # ttl в DATA
    bytes([1, P.DATA, 0, 0]) + ID + bytes(P.MAX_DATA + 1),
])
def test_malformed(raw):
    with pytest.raises(P.MeshProtocolError):
        P.decode(raw)


def test_tags_rotate_hourly_and_need_key():
    key = tag_key(b"\x07" * 32)
    assert len(key) == 32 and key != tag_key(b"\x08" * 32)
    assert tag_for_hour(key, 5) != tag_for_hour(key, 6)
    assert len(tag_for_hour(key, 5)) == 32
    assert hour_of(7200.5) == 2
