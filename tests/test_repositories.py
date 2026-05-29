from mys_crypto.secure import SecureBytes
from mys_storage import kdf


def test_derive_db_key_deterministic_and_secure():
    salt = b"saltsaltsaltsalt"
    k1 = kdf.derive_db_key(b"pw", salt, time_cost=1, memory_cost=8, parallelism=1, hash_len=32)
    k2 = kdf.derive_db_key(b"pw", salt, time_cost=1, memory_cost=8, parallelism=1, hash_len=32)
    assert isinstance(k1, SecureBytes)
    assert bytes(k1) == bytes(k2)
    assert len(k1) == 32


def test_derive_db_key_salt_sensitive():
    a = kdf.derive_db_key(b"pw", b"AAAAAAAAAAAAAAAA", time_cost=1, memory_cost=8, parallelism=1)
    b = kdf.derive_db_key(b"pw", b"BBBBBBBBBBBBBBBB", time_cost=1, memory_cost=8, parallelism=1)
    assert bytes(a) != bytes(b)
