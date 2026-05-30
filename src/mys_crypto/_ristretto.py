"""Тонкая ctypes-обёртка над ristretto255 из libsodium.

Зачем ctypes, а не PyNaCl: колесо PyNaCl не экспонирует символы
``crypto_core_ristretto255_*`` ни на одном уровне (проверено на 1.6.2), хотя
libsodium их содержит. Системный libsodium (>= 1.0.18) даёт аудированный
ristretto255 — проверенный примитив ровно под ciphersuite CPace-ristretto255.
Здесь только вызовы libsodium: ни математики группы, ни I/O.

Модуль приватный: наружу ristretto255 уходит через :mod:`mys_crypto.pake`.
"""

import ctypes
from ctypes.util import find_library


class RistrettoError(Exception):
    """Невалидная точка/скаляр или identity-результат scalarmult."""


def _load() -> ctypes.CDLL:
    candidates = [find_library("sodium"), "libsodium.so.26", "libsodium.so"]
    last: OSError | None = None
    for name in candidates:
        if not name:
            continue
        try:
            return ctypes.CDLL(name)
        except OSError as exc:  # pragma: no cover - зависит от системы
            last = exc
    raise RistrettoError(
        "libsodium с ristretto255 не найден (нужен libsodium >= 1.0.18)"
    ) from last


_lib = _load()
if _lib.sodium_init() < 0:  # pragma: no cover - libsodium инициализируется один раз
    raise RistrettoError("sodium_init() провалился")

BYTES = 32        # размер точки ristretto255
HASHBYTES = 64    # вход для from_hash (SHA-512)
SCALARBYTES = 32  # размер скаляра

_c = _lib.crypto_core_ristretto255_from_hash
_c.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
_c.restype = ctypes.c_int

_s = _lib.crypto_scalarmult_ristretto255
_s.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
_s.restype = ctypes.c_int

_sb = _lib.crypto_scalarmult_ristretto255_base
_sb.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
_sb.restype = ctypes.c_int

_rand = _lib.crypto_core_ristretto255_scalar_random
_rand.argtypes = [ctypes.c_char_p]
_rand.restype = None

_valid = _lib.crypto_core_ristretto255_is_valid_point
_valid.argtypes = [ctypes.c_char_p]
_valid.restype = ctypes.c_int


def from_hash(h: bytes) -> bytes:
    """Map-to-group: 64-байтовый хеш → точка ristretto255 (32 байта)."""
    if len(h) != HASHBYTES:
        raise RistrettoError(f"from_hash ждёт {HASHBYTES} байт, дано {len(h)}")
    out = ctypes.create_string_buffer(BYTES)
    if _c(out, h) != 0:  # pragma: no cover - from_hash не отказывает на 64 байтах
        raise RistrettoError("from_hash провалился")
    return out.raw


def scalarmult(scalar: bytes, point: bytes) -> bytes:
    """q = scalar·point. Отказ (RistrettoError), если point/результат — identity."""
    if len(scalar) != SCALARBYTES or len(point) != BYTES:
        raise RistrettoError("неверная длина скаляра или точки")
    out = ctypes.create_string_buffer(BYTES)
    if _s(out, scalar, point) != 0:
        raise RistrettoError("scalarmult: identity или невалидная точка")
    return out.raw


def scalarmult_base(scalar: bytes) -> bytes:
    """q = scalar·B (базовая точка)."""
    if len(scalar) != SCALARBYTES:
        raise RistrettoError("неверная длина скаляра")
    out = ctypes.create_string_buffer(BYTES)
    if _sb(out, scalar) != 0:
        raise RistrettoError("scalarmult_base: identity-результат")
    return out.raw


def scalar_random() -> bytes:
    """Равномерный случайный скаляр в [0, L)."""
    out = ctypes.create_string_buffer(SCALARBYTES)
    _rand(out)
    return out.raw


def is_valid_point(point: bytes) -> bool:
    """Каноническая, не-identity точка ristretto255 в подгруппе порядка L."""
    return len(point) == BYTES and _valid(point) == 1
