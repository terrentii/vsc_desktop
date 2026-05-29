from mys_crypto.secure import SecureBytes


def test_holds_and_exposes_bytes():
    sb = SecureBytes(b"\x01\x02\x03")
    assert bytes(sb) == b"\x01\x02\x03"
    assert len(sb) == 3
    assert sb.hex() == "010203"


def test_wipe_zeroizes():
    sb = SecureBytes(b"secret-key-material")
    sb.wipe()
    assert bytes(sb) == bytes(len(b"secret-key-material"))


def test_context_manager_wipes_on_exit():
    with SecureBytes(b"\xaa" * 32) as sb:
        assert bytes(sb) != bytes(32)
    assert bytes(sb) == bytes(32)
