"""Вывод ключа БД из мастер-пароля (Argon2id)."""

from mys_crypto import primitives
from mys_crypto.secure import SecureBytes


def derive_db_key(
    password: bytes,
    salt: bytes,
    *,
    time_cost: int = 3,
    memory_cost: int = 262144,
    parallelism: int = 4,
    hash_len: int = 32,
) -> SecureBytes:
    raw = primitives.argon2id(
        password, salt, hash_len,
        time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism,
    )
    return SecureBytes(raw)
