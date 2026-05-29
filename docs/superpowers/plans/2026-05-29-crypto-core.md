# Крипто-ядро (mys_crypto) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Построить криптографическое ядро `mys_crypto`: проверенные примитивы, обратимый мат. слой МЫС-transform, Double Ratchet (forward secrecy) и конверт сообщений, объединяющий их.

**Architecture:** Гарантию безопасности дают проверенные примитивы (`cryptography`, `argon2-cffi`). МЫС-transform — обратимая ключевая биекция, применяемая поверх AEAD-шифротекста, поэтому не может ослабить защиту. Double Ratchet реализован по спецификации Signal (KDF-цепочки + DH-ratchet + пропущенные ключи). Конверт связывает всё: `ratchet_encrypt` → wire → МЫС-transform.

**Tech Stack:** Python 3.13, `cryptography`, `argon2-cffi`, `pytest`.

---

## Структура файлов

```
src/mys_crypto/
  __init__.py          # экспорт публичного API
  primitives.py        # X25519, Ed25519, ChaCha20-Poly1305, HKDF, Argon2id
  transform.py         # МЫС-transform: keystream + S-box + encode/decode
  ratchet.py           # KDF-цепочки, Header, RatchetState, encrypt/decrypt
  envelope.py          # seal/open: ratchet-wire + МЫС-transform
tests/
  __init__.py
  test_primitives.py
  test_transform.py
  test_ratchet.py
  test_envelope.py
  test_integration.py
pyproject.toml
pytest.ini
```

**Зоны ответственности:** `primitives` не знает о ratchet и transform. `transform` работает только с байтами и ключом. `ratchet` использует `primitives`, но не `transform`. `envelope` связывает `ratchet` и `transform`. Каждый файл — одна ответственность.

---

### Task 1: Каркас проекта и зависимости

**Files:**
- Create: `pyproject.toml`
- Create: `pytest.ini`
- Create: `src/mys_crypto/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Создать `pyproject.toml`**

```toml
[project]
name = "mys-crypto"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "cryptography>=42.0",
    "argon2-cffi>=23.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Создать `pytest.ini`**

```ini
[pytest]
pythonpath = src
testpaths = tests
```

- [ ] **Step 3: Создать пустые `src/mys_crypto/__init__.py` и `tests/__init__.py`**

`src/mys_crypto/__init__.py`:
```python
"""Крипто-ядро МЫС Desktop."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Установить зависимости**

Run: `.venv/bin/pip install "cryptography>=42.0" "argon2-cffi>=23.1" "pytest>=8.0"`
Expected: успешная установка без ошибок.

- [ ] **Step 5: Проверить, что pytest запускается**

Run: `.venv/bin/pytest -q`
Expected: `no tests ran` (0 собранных тестов, без ошибок импорта).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml pytest.ini src/mys_crypto/__init__.py tests/__init__.py
git commit -m "chore: scaffold mys_crypto package and pytest"
```

---

### Task 2: Примитив X25519

**Files:**
- Create: `src/mys_crypto/primitives.py`
- Test: `tests/test_primitives.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_primitives.py`:
```python
from mys_crypto import primitives


def test_x25519_shared_secret_agreement():
    a_priv, a_pub = primitives.generate_x25519_keypair()
    b_priv, b_pub = primitives.generate_x25519_keypair()
    assert len(a_pub) == 32 and len(a_priv) == 32
    secret_a = primitives.x25519_shared(a_priv, b_pub)
    secret_b = primitives.x25519_shared(b_priv, a_pub)
    assert secret_a == secret_b
    assert len(secret_a) == 32


def test_x25519_keys_are_random():
    _, pub1 = primitives.generate_x25519_keypair()
    _, pub2 = primitives.generate_x25519_keypair()
    assert pub1 != pub2
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv/bin/pytest tests/test_primitives.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError: generate_x25519_keypair`.

- [ ] **Step 3: Минимальная реализация**

`src/mys_crypto/primitives.py`:
```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

_RAW = serialization.Encoding.Raw
_PUB_RAW = serialization.PublicFormat.Raw
_PRIV_RAW = serialization.PrivateFormat.Raw
_NOENC = serialization.NoEncryption()


def generate_x25519_keypair() -> tuple[bytes, bytes]:
    priv = X25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(_RAW, _PRIV_RAW, _NOENC)
    pub_bytes = priv.public_key().public_bytes(_RAW, _PUB_RAW)
    return priv_bytes, pub_bytes


def x25519_shared(private_bytes: bytes, peer_public_bytes: bytes) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(private_bytes)
    peer = X25519PublicKey.from_public_bytes(peer_public_bytes)
    return priv.exchange(peer)
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_primitives.py -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/primitives.py tests/test_primitives.py
git commit -m "feat: add X25519 key exchange primitive"
```

---

### Task 3: Примитив Ed25519

**Files:**
- Modify: `src/mys_crypto/primitives.py`
- Test: `tests/test_primitives.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_primitives.py`:
```python
def test_ed25519_sign_verify():
    priv, pub = primitives.generate_ed25519_keypair()
    msg = b"mys message"
    sig = primitives.ed25519_sign(priv, msg)
    assert primitives.ed25519_verify(pub, sig, msg) is True


def test_ed25519_rejects_tampered_message():
    priv, pub = primitives.generate_ed25519_keypair()
    sig = primitives.ed25519_sign(priv, b"original")
    assert primitives.ed25519_verify(pub, sig, b"tampered") is False
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_primitives.py -k ed25519 -v`
Expected: FAIL — `AttributeError: generate_ed25519_keypair`.

- [ ] **Step 3: Реализация**

Добавить в `src/mys_crypto/primitives.py` (импорты — вверху файла):
```python
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
```

Функции:
```python
def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(_RAW, _PRIV_RAW, _NOENC)
    pub_bytes = priv.public_key().public_bytes(_RAW, _PUB_RAW)
    return priv_bytes, pub_bytes


def ed25519_sign(private_bytes: bytes, message: bytes) -> bytes:
    priv = Ed25519PrivateKey.from_private_bytes(private_bytes)
    return priv.sign(message)


def ed25519_verify(public_bytes: bytes, signature: bytes, message: bytes) -> bool:
    pub = Ed25519PublicKey.from_public_bytes(public_bytes)
    try:
        pub.verify(signature, message)
        return True
    except InvalidSignature:
        return False
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_primitives.py -k ed25519 -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/primitives.py tests/test_primitives.py
git commit -m "feat: add Ed25519 sign/verify primitive"
```

---

### Task 4: Примитив AEAD (ChaCha20-Poly1305)

**Files:**
- Modify: `src/mys_crypto/primitives.py`
- Test: `tests/test_primitives.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_primitives.py`:
```python
import pytest


def test_aead_round_trip():
    key = b"k" * 32
    nonce = b"n" * 12
    pt = b"secret payload"
    aad = b"header"
    ct = primitives.aead_encrypt(key, nonce, pt, aad)
    assert ct != pt
    assert primitives.aead_decrypt(key, nonce, ct, aad) == pt


def test_aead_rejects_wrong_aad():
    key = b"k" * 32
    nonce = b"n" * 12
    ct = primitives.aead_encrypt(key, nonce, b"data", b"aad1")
    with pytest.raises(Exception):
        primitives.aead_decrypt(key, nonce, ct, b"aad2")
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_primitives.py -k aead -v`
Expected: FAIL — `AttributeError: aead_encrypt`.

- [ ] **Step 3: Реализация**

Добавить в `src/mys_crypto/primitives.py` (импорт вверху):
```python
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
```

Функции:
```python
def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    return ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)


def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_primitives.py -k aead -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/primitives.py tests/test_primitives.py
git commit -m "feat: add ChaCha20-Poly1305 AEAD primitive"
```

---

### Task 5: Примитивы HKDF и Argon2id

**Files:**
- Modify: `src/mys_crypto/primitives.py`
- Test: `tests/test_primitives.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_primitives.py`:
```python
def test_hkdf_deterministic_and_length():
    ikm = b"input key material"
    out1 = primitives.hkdf(ikm, 64, salt=b"salt", info=b"info")
    out2 = primitives.hkdf(ikm, 64, salt=b"salt", info=b"info")
    assert out1 == out2
    assert len(out1) == 64
    out3 = primitives.hkdf(ikm, 64, salt=b"salt", info=b"other")
    assert out3 != out1


def test_argon2id_deterministic_and_salt_sensitive():
    h1 = primitives.argon2id(b"password", b"saltsaltsaltsalt", 32)
    h2 = primitives.argon2id(b"password", b"saltsaltsaltsalt", 32)
    h3 = primitives.argon2id(b"password", b"DIFFERENTsaltxxx", 32)
    assert h1 == h2
    assert len(h1) == 32
    assert h1 != h3
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_primitives.py -k "hkdf or argon2id" -v`
Expected: FAIL — `AttributeError: hkdf`.

- [ ] **Step 3: Реализация**

Добавить в `src/mys_crypto/primitives.py` (импорты вверху):
```python
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from argon2.low_level import Type, hash_secret_raw
```

Функции:
```python
def hkdf(ikm: bytes, length: int, salt: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
    ).derive(ikm)


def argon2id(
    password: bytes,
    salt: bytes,
    length: int,
    time_cost: int = 3,
    memory_cost: int = 65536,
    parallelism: int = 4,
) -> bytes:
    return hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=length,
        type=Type.ID,
    )
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_primitives.py -k "hkdf or argon2id" -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/primitives.py tests/test_primitives.py
git commit -m "feat: add HKDF and Argon2id primitives"
```

---

### Task 6: МЫС-transform

**Files:**
- Create: `src/mys_crypto/transform.py`
- Test: `tests/test_transform.py`

МЫС-transform — обратимая ключевая биекция: к каждому байту прибавляется байт keystream (mod 256), затем применяется ключевой S-box. Декодирование выполняет обратные операции. Keystream строится ChaCha20 (произвольная длина), S-box — ключевой перестановкой Фишера–Йетса.

- [ ] **Step 1: Написать падающий тест**

`tests/test_transform.py`:
```python
import pytest
from mys_crypto import transform


@pytest.mark.parametrize("size", [0, 1, 15, 256, 1000, 10000])
def test_transform_is_bijection(size):
    key = b"transform-key-32-bytes-long!!!!!"
    data = bytes((i * 7) % 256 for i in range(size))
    encoded = transform.transform_encode(data, key)
    assert transform.transform_decode(encoded, key) == data


def test_transform_changes_data():
    key = b"transform-key-32-bytes-long!!!!!"
    data = b"plain ciphertext bytes here"
    assert transform.transform_encode(data, key) != data


def test_transform_key_dependent():
    data = b"same input bytes"
    a = transform.transform_encode(data, b"A" * 32)
    b = transform.transform_encode(data, b"B" * 32)
    assert a != b
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: mys_crypto.transform`.

- [ ] **Step 3: Реализация**

`src/mys_crypto/transform.py`:
```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

from .primitives import hkdf


def _keystream(key: bytes, length: int) -> bytes:
    if length == 0:
        return b""
    subkey = hkdf(key, 32, salt=b"", info=b"mys-transform-ks-key")
    nonce = bytes(16)
    cipher = Cipher(algorithms.ChaCha20(subkey, nonce), mode=None)
    return cipher.encryptor().update(bytes(length))


def _build_sbox(key: bytes) -> tuple[list[int], list[int]]:
    stream = hkdf(key, 256, salt=b"", info=b"mys-transform-sbox")
    sbox = list(range(256))
    for i in range(255, 0, -1):
        j = stream[255 - i] % (i + 1)
        sbox[i], sbox[j] = sbox[j], sbox[i]
    inv = [0] * 256
    for index, value in enumerate(sbox):
        inv[value] = index
    return sbox, inv


def transform_encode(data: bytes, key: bytes) -> bytes:
    ks = _keystream(key, len(data))
    sbox, _ = _build_sbox(key)
    return bytes(sbox[(b + ks[i]) & 0xFF] for i, b in enumerate(data))


def transform_decode(data: bytes, key: bytes) -> bytes:
    ks = _keystream(key, len(data))
    _, inv = _build_sbox(key)
    return bytes((inv[b] - ks[i]) & 0xFF for i, b in enumerate(data))
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: PASS (8 тестов: 6 параметров биекции + 2).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/transform.py tests/test_transform.py
git commit -m "feat: add МЫС-transform reversible keyed layer"
```

---

### Task 7: KDF-цепочки ratchet

**Files:**
- Create: `src/mys_crypto/ratchet.py`
- Test: `tests/test_ratchet.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_ratchet.py`:
```python
from mys_crypto import ratchet


def test_kdf_rk_shapes_and_determinism():
    rk = b"r" * 32
    dh_out = b"d" * 32
    new_rk1, ck1 = ratchet.kdf_rk(rk, dh_out)
    new_rk2, ck2 = ratchet.kdf_rk(rk, dh_out)
    assert (new_rk1, ck1) == (new_rk2, ck2)
    assert len(new_rk1) == 32 and len(ck1) == 32
    assert new_rk1 != rk


def test_kdf_ck_advances():
    ck = b"c" * 32
    new_ck, mk = ratchet.kdf_ck(ck)
    assert len(new_ck) == 32 and len(mk) == 32
    assert new_ck != ck and mk != ck
    assert new_ck != mk


def test_derive_message_keys_shapes():
    key, nonce = ratchet.derive_message_keys(b"m" * 32)
    assert len(key) == 32 and len(nonce) == 12
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_ratchet.py -k kdf -v`
Expected: FAIL — `AttributeError: kdf_rk`.

- [ ] **Step 3: Реализация**

`src/mys_crypto/ratchet.py`:
```python
import hashlib
import hmac

from .primitives import hkdf


def kdf_rk(rk: bytes, dh_out: bytes) -> tuple[bytes, bytes]:
    out = hkdf(dh_out, 64, salt=rk, info=b"mys-ratchet-rk")
    return out[:32], out[32:]


def kdf_ck(ck: bytes) -> tuple[bytes, bytes]:
    mk = hmac.new(ck, b"\x01", hashlib.sha256).digest()
    new_ck = hmac.new(ck, b"\x02", hashlib.sha256).digest()
    return new_ck, mk


def derive_message_keys(mk: bytes) -> tuple[bytes, bytes]:
    out = hkdf(mk, 44, salt=bytes(32), info=b"mys-ratchet-msg")
    return out[:32], out[32:44]
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_ratchet.py -k kdf -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/ratchet.py tests/test_ratchet.py
git commit -m "feat: add ratchet KDF chains"
```

---

### Task 8: Заголовок сообщения ratchet

**Files:**
- Modify: `src/mys_crypto/ratchet.py`
- Test: `tests/test_ratchet.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_ratchet.py`:
```python
def test_header_serialize_round_trip():
    dh = b"p" * 32
    h = ratchet.Header(dh=dh, pn=5, n=42)
    blob = h.serialize()
    assert len(blob) == 40
    restored = ratchet.Header.deserialize(blob)
    assert restored.dh == dh
    assert restored.pn == 5
    assert restored.n == 42
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_ratchet.py -k header -v`
Expected: FAIL — `AttributeError: Header`.

- [ ] **Step 3: Реализация**

Добавить в `src/mys_crypto/ratchet.py` (импорт вверху файла):
```python
from dataclasses import dataclass
```

Класс:
```python
@dataclass
class Header:
    dh: bytes
    pn: int
    n: int

    def serialize(self) -> bytes:
        return self.dh + self.pn.to_bytes(4, "big") + self.n.to_bytes(4, "big")

    @classmethod
    def deserialize(cls, blob: bytes) -> "Header":
        return cls(
            dh=blob[:32],
            pn=int.from_bytes(blob[32:36], "big"),
            n=int.from_bytes(blob[36:40], "big"),
        )
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_ratchet.py -k header -v`
Expected: PASS (1 тест).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/ratchet.py tests/test_ratchet.py
git commit -m "feat: add ratchet message header"
```

---

### Task 9: Инициализация состояния ratchet

**Files:**
- Modify: `src/mys_crypto/ratchet.py`
- Test: `tests/test_ratchet.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_ratchet.py` (импорт вверху файла теста):
```python
from mys_crypto import primitives
```

Тест:
```python
def test_ratchet_init_alice_and_bob():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    assert alice.dhr == bob_pub
    assert alice.cks is not None and alice.ckr is None
    assert bob.dhr is None and bob.rk == sk
    assert bob.cks is None and bob.ckr is None
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_ratchet.py -k init -v`
Expected: FAIL — `AttributeError: ratchet_init_alice`.

- [ ] **Step 3: Реализация**

Добавить в `src/mys_crypto/ratchet.py` (импорт вверху файла):
```python
from .primitives import generate_x25519_keypair, x25519_shared
```

State и init:
```python
@dataclass
class RatchetState:
    dhs: tuple[bytes, bytes]
    dhr: bytes | None
    rk: bytes
    cks: bytes | None
    ckr: bytes | None
    ns: int
    nr: int
    pn: int
    mkskipped: dict[tuple[bytes, int], bytes]


def ratchet_init_alice(sk: bytes, bob_dh_pub: bytes) -> RatchetState:
    dhs = generate_x25519_keypair()
    rk, cks = kdf_rk(sk, x25519_shared(dhs[0], bob_dh_pub))
    return RatchetState(
        dhs=dhs, dhr=bob_dh_pub, rk=rk, cks=cks, ckr=None,
        ns=0, nr=0, pn=0, mkskipped={},
    )


def ratchet_init_bob(sk: bytes, bob_dh_keypair: tuple[bytes, bytes]) -> RatchetState:
    return RatchetState(
        dhs=bob_dh_keypair, dhr=None, rk=sk, cks=None, ckr=None,
        ns=0, nr=0, pn=0, mkskipped={},
    )
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_ratchet.py -k init -v`
Expected: PASS (1 тест).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/ratchet.py tests/test_ratchet.py
git commit -m "feat: add ratchet state initialization"
```

---

### Task 10: Шифрование/дешифрование ratchet (DH-ratchet + пропущенные ключи)

**Files:**
- Modify: `src/mys_crypto/ratchet.py`
- Test: `tests/test_ratchet.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_ratchet.py`:
```python
def _pair():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    return alice, bob


def test_ratchet_single_message():
    alice, bob = _pair()
    hdr, ct = ratchet.ratchet_encrypt(alice, b"hello bob")
    assert ratchet.ratchet_decrypt(bob, hdr, ct) == b"hello bob"


def test_ratchet_bidirectional_conversation():
    alice, bob = _pair()
    h1, c1 = ratchet.ratchet_encrypt(alice, b"a1")
    assert ratchet.ratchet_decrypt(bob, h1, c1) == b"a1"
    h2, c2 = ratchet.ratchet_encrypt(bob, b"b1")
    assert ratchet.ratchet_decrypt(alice, h2, c2) == b"b1"
    h3, c3 = ratchet.ratchet_encrypt(alice, b"a2")
    assert ratchet.ratchet_decrypt(bob, h3, c3) == b"a2"


def test_ratchet_out_of_order():
    alice, bob = _pair()
    h1, c1 = ratchet.ratchet_encrypt(alice, b"first")
    h2, c2 = ratchet.ratchet_encrypt(alice, b"second")
    # доставка во втором порядке: сначала second, потом first
    assert ratchet.ratchet_decrypt(bob, h2, c2) == b"second"
    assert ratchet.ratchet_decrypt(bob, h1, c1) == b"first"


def test_ratchet_rejects_tampered_ciphertext():
    import pytest
    alice, bob = _pair()
    hdr, ct = ratchet.ratchet_encrypt(alice, b"intact")
    tampered = bytes([ct[0] ^ 0x01]) + ct[1:]
    with pytest.raises(Exception):
        ratchet.ratchet_decrypt(bob, hdr, tampered)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_ratchet.py -k "single or bidirectional or out_of_order or tampered" -v`
Expected: FAIL — `AttributeError: ratchet_encrypt`.

- [ ] **Step 3: Реализация**

Добавить в `src/mys_crypto/ratchet.py` (импорт вверху файла):
```python
from .primitives import aead_decrypt, aead_encrypt
```

Константа и функции:
```python
MAX_SKIP = 1000


def ratchet_encrypt(state: RatchetState, plaintext: bytes, ad: bytes = b"") -> tuple[Header, bytes]:
    state.cks, mk = kdf_ck(state.cks)
    header = Header(dh=state.dhs[1], pn=state.pn, n=state.ns)
    state.ns += 1
    key, nonce = derive_message_keys(mk)
    ct = aead_encrypt(key, nonce, plaintext, ad + header.serialize())
    return header, ct


def ratchet_decrypt(state: RatchetState, header: Header, ciphertext: bytes, ad: bytes = b"") -> bytes:
    skipped = _try_skipped(state, header, ciphertext, ad)
    if skipped is not None:
        return skipped
    if header.dh != state.dhr:
        _skip_message_keys(state, header.pn)
        _dh_ratchet(state, header)
    _skip_message_keys(state, header.n)
    state.ckr, mk = kdf_ck(state.ckr)
    state.nr += 1
    key, nonce = derive_message_keys(mk)
    return aead_decrypt(key, nonce, ciphertext, ad + header.serialize())


def _try_skipped(state: RatchetState, header: Header, ciphertext: bytes, ad: bytes) -> bytes | None:
    key_id = (header.dh, header.n)
    if key_id not in state.mkskipped:
        return None
    mk = state.mkskipped.pop(key_id)
    key, nonce = derive_message_keys(mk)
    return aead_decrypt(key, nonce, ciphertext, ad + header.serialize())


def _skip_message_keys(state: RatchetState, until: int) -> None:
    if state.ckr is None:
        return
    if state.nr + MAX_SKIP < until:
        raise ValueError("too many skipped messages")
    while state.nr < until:
        state.ckr, mk = kdf_ck(state.ckr)
        state.mkskipped[(state.dhr, state.nr)] = mk
        state.nr += 1


def _dh_ratchet(state: RatchetState, header: Header) -> None:
    state.pn = state.ns
    state.ns = 0
    state.nr = 0
    state.dhr = header.dh
    state.rk, state.ckr = kdf_rk(state.rk, x25519_shared(state.dhs[0], state.dhr))
    state.dhs = generate_x25519_keypair()
    state.rk, state.cks = kdf_rk(state.rk, x25519_shared(state.dhs[0], state.dhr))
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_ratchet.py -v`
Expected: PASS (все тесты ratchet).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/ratchet.py tests/test_ratchet.py
git commit -m "feat: implement Double Ratchet encrypt/decrypt"
```

---

### Task 11: Конверт сообщений (ratchet + МЫС-transform)

**Files:**
- Create: `src/mys_crypto/envelope.py`
- Test: `tests/test_envelope.py`

Конверт сериализует `(Header, ciphertext)` в wire-формат и оборачивает его МЫС-transform. На приёме transform снимается ПЕРВЫМ, затем расшифровывается ratchet — инвариант безопасности соблюдён.

- [ ] **Step 1: Написать падающий тест**

`tests/test_envelope.py`:
```python
import pytest

from mys_crypto import envelope, primitives, ratchet, transform


def _pair_with_tkey():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    tkey = envelope.derive_transform_key(sk)
    return alice, bob, tkey


def test_envelope_round_trip():
    alice, bob, tkey = _pair_with_tkey()
    blob = envelope.seal(alice, tkey, b"hi through envelope")
    assert envelope.open_(bob, tkey, blob) == b"hi through envelope"


def test_envelope_transform_is_outer_layer():
    # Снять transform с blob и убедиться, что внутри лежит валидный ratchet-wire,
    # который расшифровывается обычным ratchet_decrypt.
    alice, bob, tkey = _pair_with_tkey()
    blob = envelope.seal(alice, tkey, b"inner check")
    wire = transform.transform_decode(blob, tkey)
    header = ratchet.Header.deserialize(wire[:40])
    ct = wire[40:]
    assert ratchet.ratchet_decrypt(bob, header, ct) == b"inner check"


def test_envelope_rejects_tampered_blob():
    alice, bob, tkey = _pair_with_tkey()
    blob = envelope.seal(alice, tkey, b"intact")
    tampered = bytes([blob[-1] ^ 0x01]) + blob[1:] if len(blob) == 1 else blob[:-1] + bytes([blob[-1] ^ 0x01])
    with pytest.raises(Exception):
        envelope.open_(bob, tkey, tampered)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: mys_crypto.envelope`.

- [ ] **Step 3: Реализация**

`src/mys_crypto/envelope.py`:
```python
from .primitives import hkdf
from .ratchet import Header, RatchetState, ratchet_decrypt, ratchet_encrypt
from .transform import transform_decode, transform_encode


def derive_transform_key(sk: bytes) -> bytes:
    return hkdf(sk, 32, salt=b"", info=b"mys-transform-master")


def seal(state: RatchetState, transform_key: bytes, plaintext: bytes, ad: bytes = b"") -> bytes:
    header, ct = ratchet_encrypt(state, plaintext, ad)
    wire = header.serialize() + ct
    return transform_encode(wire, transform_key)


def open_(state: RatchetState, transform_key: bytes, blob: bytes, ad: bytes = b"") -> bytes:
    wire = transform_decode(blob, transform_key)
    header = Header.deserialize(wire[:40])
    ct = wire[40:]
    return ratchet_decrypt(state, header, ct, ad)
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_envelope.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Экспортировать публичный API**

Заменить содержимое `src/mys_crypto/__init__.py`:
```python
"""Крипто-ядро МЫС Desktop."""

from . import envelope, primitives, ratchet, transform

__all__ = ["primitives", "transform", "ratchet", "envelope"]
```

- [ ] **Step 6: Commit**

```bash
git add src/mys_crypto/envelope.py src/mys_crypto/__init__.py tests/test_envelope.py
git commit -m "feat: add message envelope combining ratchet and МЫС-transform"
```

---

### Task 12: Интеграционный тест — полный диалог

**Files:**
- Test: `tests/test_integration.py`

- [ ] **Step 1: Написать тест**

`tests/test_integration.py`:
```python
from mys_crypto import envelope, primitives, ratchet


def _session():
    sk = b"z" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    tkey = envelope.derive_transform_key(sk)
    return alice, bob, tkey


def test_full_bidirectional_conversation():
    alice, bob, tkey = _session()
    # Alice -> Bob (несколько подряд)
    for i in range(3):
        blob = envelope.seal(alice, tkey, f"a{i}".encode())
        assert envelope.open_(bob, tkey, blob) == f"a{i}".encode()
    # Bob -> Alice (DH-ratchet)
    blob = envelope.seal(bob, tkey, b"reply")
    assert envelope.open_(alice, tkey, blob) == b"reply"
    # Alice -> Bob снова
    blob = envelope.seal(alice, tkey, b"after ratchet")
    assert envelope.open_(bob, tkey, blob) == b"after ratchet"


def test_out_of_order_delivery_through_envelope():
    alice, bob, tkey = _session()
    blob1 = envelope.seal(alice, tkey, b"msg-1")
    blob2 = envelope.seal(alice, tkey, b"msg-2")
    blob3 = envelope.seal(alice, tkey, b"msg-3")
    # доставка: 3, 1, 2
    assert envelope.open_(bob, tkey, blob3) == b"msg-3"
    assert envelope.open_(bob, tkey, blob1) == b"msg-1"
    assert envelope.open_(bob, tkey, blob2) == b"msg-2"
```

- [ ] **Step 2: Запустить весь набор тестов**

Run: `.venv/bin/pytest -v`
Expected: PASS — все тесты крипто-ядра проходят.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add full conversation integration tests"
```

---

## Самопроверка плана

**Покрытие спецификации (раздел 4 «МЫС-Crypto»):**
- Argon2id — Task 5 ✓
- X25519 — Task 2 ✓
- Ed25519 — Task 3 ✓
- ChaCha20-Poly1305 (AEAD) — Task 4 ✓
- HKDF-SHA256 — Task 5 ✓
- Double Ratchet — Tasks 7–10 ✓
- МЫС-transform (биекция, ключ из независимого HKDF-`info`, поверх AEAD, тест обратимости) — Task 6 + Task 11 ✓
- Инвариант «transform поверх AEAD» — проверяется `test_envelope_transform_is_outer_layer` ✓
- PAKE — **намеренно вне крипто-ядра** (относится к децентрализованному модулю, под-проект №4).

**Согласованность имён:** `generate_x25519_keypair`, `x25519_shared`, `hkdf`, `aead_encrypt/decrypt`, `kdf_rk/kdf_ck`, `derive_message_keys`, `Header`, `RatchetState`, `ratchet_encrypt/decrypt`, `transform_encode/decode`, `seal/open_`, `derive_transform_key` — используются единообразно во всех задачах и тестах.

**Плейсхолдеры:** отсутствуют — каждый шаг содержит полный код и точные команды.
