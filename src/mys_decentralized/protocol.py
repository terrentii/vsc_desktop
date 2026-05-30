"""Wire-протокол: деривация room_id/prs, фрейминг, сериализация сообщений.

Чистые байты и деривация — ни сокетов, ни крипто-склейки (граница CLAUDE.md:
сеть оперирует непрозрачными кадрами). Сервер видит только ``room_id`` и
непрозрачный payload; фраза и открытый текст сюда не попадают.

Кадр: ``u8 type | u8 flags | u32 length | payload`` (big-endian).
"""

import hashlib
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .errors import TransportError

Candidate = tuple[str, int]

_HEADER = 6  # u8 type + u8 flags + u32 length


# --- деривация room_id / prs из фразы ----------------------------------------

def derive_room_params(phrase: str) -> tuple[bytes, bytes]:
    """Фраза → ``(room_id, prs)``: независимые значения (§3 спеки).

    ``room_id`` отдаётся серверу, ``prs`` (вход CPace) не покидает клиент. Оба
    выводятся из общего seed разными HKDF-``info``, так что по ``room_id`` нельзя
    восстановить ни фразу, ни ``prs``.
    """
    norm = unicodedata.normalize("NFKC", phrase).strip().encode("utf-8")
    seed = hashlib.blake2b(norm, digest_size=32, person=b"mys-phrase").digest()
    room_id = _hkdf(seed, b"mys-room-id")
    prs = _hkdf(seed, b"mys-pake-prs")
    return room_id, prs


def _hkdf(ikm: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"", info=info).derive(ikm)


# --- типы сообщений ----------------------------------------------------------

class MsgType(IntEnum):
    HELLO = 1       # клиент → сервер: вход в комнату
    PAIR = 2        # сервер → клиент: роль и кандидаты пира
    PUNCH = 3       # клиент↔клиент: hole-punch проба
    PUNCH_ACK = 4   # клиент↔клиент: подтверждение прямого пути
    RELAY = 5       # клиент↔сервер↔клиент: ретрансляция непрозрачного payload
    PAKE = 6        # CPace-сообщение (Y) — открыто по дизайну PAKE
    CONFIRM = 7     # key-confirmation MAC
    DATA = 8        # E2E-защищённый envelope.seal(...)


class Role(IntEnum):
    INITIATOR = 0   # первый в комнате: Alice в ratchet, лекс. первый в CPace
    RESPONDER = 1   # второй в комнате: Bob


# --- фрейминг ----------------------------------------------------------------

def encode_frame(mtype: MsgType, payload: bytes, flags: int = 0) -> bytes:
    return bytes([int(mtype), flags & 0xFF]) + len(payload).to_bytes(4, "big") + payload


def decode_frame(buf: bytes | bytearray) -> tuple[MsgType, int, bytes, int]:
    """Разобрать один кадр из начала ``buf``.

    Возвращает ``(type, flags, payload, consumed)``; ``consumed`` — сколько байт
    занял кадр (хвост после него — следующий кадр в потоке). Бросает
    ``TransportError`` на усечённом заголовке/неполном payload.
    """
    if len(buf) < _HEADER:
        raise TransportError("усечённый заголовок кадра")
    raw_type = buf[0]
    flags = buf[1]
    length = int.from_bytes(buf[2:6], "big")
    end = _HEADER + length
    if len(buf) < end:
        raise TransportError("неполный payload кадра")
    try:
        mtype = MsgType(raw_type)
    except ValueError as exc:
        raise TransportError(f"неизвестный тип кадра {raw_type}") from exc
    return mtype, flags, bytes(buf[_HEADER:end]), end


# --- сериализация полей -------------------------------------------------------

def _put_var(buf: bytearray, chunk: bytes) -> None:
    buf += len(chunk).to_bytes(2, "big")
    buf += chunk


def _get_var(mv: memoryview, pos: int) -> tuple[bytes, int]:
    if pos + 2 > len(mv):
        raise TransportError("усечённое поле переменной длины")
    n = int.from_bytes(mv[pos:pos + 2], "big")
    pos += 2
    if pos + n > len(mv):
        raise TransportError("поле переменной длины выходит за payload")
    return bytes(mv[pos:pos + n]), pos + n


def _put_candidates(buf: bytearray, candidates: list[Candidate]) -> None:
    buf += len(candidates).to_bytes(1, "big")
    for host, port in candidates:
        _put_var(buf, host.encode("utf-8"))
        buf += port.to_bytes(2, "big")


def _get_candidates(mv: memoryview, pos: int) -> tuple[list[Candidate], int]:
    if pos + 1 > len(mv):
        raise TransportError("усечённый список кандидатов")
    count = mv[pos]
    pos += 1
    out: list[Candidate] = []
    for _ in range(count):
        host, pos = _get_var(mv, pos)
        if pos + 2 > len(mv):
            raise TransportError("усечённый порт кандидата")
        port = int.from_bytes(mv[pos:pos + 2], "big")
        pos += 2
        out.append((host.decode("utf-8"), port))
    return out, pos


# --- сообщения ----------------------------------------------------------------

@dataclass
class Hello:
    room_id: bytes
    candidates: list[Candidate] = field(default_factory=list)

    TYPE = MsgType.HELLO

    def payload(self) -> bytes:
        buf = bytearray()
        _put_var(buf, self.room_id)
        _put_candidates(buf, self.candidates)
        return bytes(buf)

    @classmethod
    def parse(cls, payload: bytes) -> "Hello":
        mv = memoryview(payload)
        room_id, pos = _get_var(mv, 0)
        candidates, _ = _get_candidates(mv, pos)
        return cls(room_id=room_id, candidates=candidates)


@dataclass
class Pair:
    role: Role
    peer_candidates: list[Candidate] = field(default_factory=list)

    TYPE = MsgType.PAIR

    def payload(self) -> bytes:
        buf = bytearray([int(self.role)])
        _put_candidates(buf, self.peer_candidates)
        return bytes(buf)

    @classmethod
    def parse(cls, payload: bytes) -> "Pair":
        if not payload:
            raise TransportError("пустой PAIR")
        role = Role(payload[0])
        candidates, _ = _get_candidates(memoryview(payload), 1)
        return cls(role=role, peer_candidates=candidates)


@dataclass
class Pake:
    y: bytes
    ad: bytes = b""

    TYPE = MsgType.PAKE

    def payload(self) -> bytes:
        buf = bytearray()
        _put_var(buf, self.y)
        _put_var(buf, self.ad)
        return bytes(buf)

    @classmethod
    def parse(cls, payload: bytes) -> "Pake":
        mv = memoryview(payload)
        y, pos = _get_var(mv, 0)
        ad, _ = _get_var(mv, pos)
        return cls(y=y, ad=ad)


@dataclass
class Confirm:
    mac: bytes

    TYPE = MsgType.CONFIRM

    def payload(self) -> bytes:
        return self.mac

    @classmethod
    def parse(cls, payload: bytes) -> "Confirm":
        return cls(mac=payload)


@dataclass
class Data:
    sealed: bytes

    TYPE = MsgType.DATA

    def payload(self) -> bytes:
        return self.sealed

    @classmethod
    def parse(cls, payload: bytes) -> "Data":
        return cls(sealed=payload)


class Relay:
    """Ретранслируемый непрозрачный payload. Не dataclass: имя поля совпало бы с
    методом ``payload()``."""

    TYPE = MsgType.RELAY

    def __init__(self, payload: bytes):
        self.payload_bytes = payload

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Relay) and other.payload_bytes == self.payload_bytes

    def __repr__(self) -> str:
        return f"Relay(payload={self.payload_bytes!r})"

    def payload(self) -> bytes:
        return self.payload_bytes

    @classmethod
    def parse(cls, payload: bytes) -> "Relay":
        return cls(payload=payload)


@dataclass
class Punch:
    TYPE = MsgType.PUNCH

    def payload(self) -> bytes:
        return b""

    @classmethod
    def parse(cls, payload: bytes) -> "Punch":
        return cls()


@dataclass
class PunchAck:
    TYPE = MsgType.PUNCH_ACK

    def payload(self) -> bytes:
        return b""

    @classmethod
    def parse(cls, payload: bytes) -> "PunchAck":
        return cls()


Message = Hello | Pair | Pake | Confirm | Data | Relay | Punch | PunchAck

_PARSERS: dict[MsgType, type] = {
    MsgType.HELLO: Hello,
    MsgType.PAIR: Pair,
    MsgType.PAKE: Pake,
    MsgType.CONFIRM: Confirm,
    MsgType.DATA: Data,
    MsgType.RELAY: Relay,
    MsgType.PUNCH: Punch,
    MsgType.PUNCH_ACK: PunchAck,
}


def encode_message(msg: Message) -> bytes:
    return encode_frame(msg.TYPE, msg.payload())


def decode_message(buf: bytes | bytearray) -> tuple[Message, int]:
    """Разобрать один кадр и десериализовать его в типизированное сообщение."""
    mtype, _flags, payload, consumed = decode_frame(buf)
    cls = _PARSERS.get(mtype)
    if cls is None:  # pragma: no cover - decode_frame уже отверг неизвестный тип
        raise TransportError(f"нет парсера для типа {mtype}")
    return cls.parse(payload), consumed
