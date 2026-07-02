"""Кодирование содержимого сообщений внутри ratchet-plaintext: текст и файлы.

Чистые байты и валидация — ни asyncio, ни vault, ни Qt (граница CLAUDE.md, в
духе :mod:`.protocol`). Ничего не меняет в wire-``MsgType``/фрейминге: это
формат *содержимого*, которое кладётся внутрь ``envelope.seal``/снимается
``envelope.open_`` в :mod:`.session`.

Каждое содержимое начинается с байта-тега (``KIND_*``). Файлы режутся на чанки
на уровне клиента: ни клиент, ни тестовый rendezvous-сервер не поднимают
``max_size`` у ``websockets`` (действует дефолт библиотеки ~1 МиБ на
сообщение) — целиком передавать файл одним запечатанным кадром ненадёжно на
relay-пути. ``CHUNK_SIZE`` держим с большим запасом под этим лимитом.
"""

import math
from dataclasses import dataclass

from .errors import TransportError

KIND_TEXT = 0x00
KIND_FILE_META = 0x01
KIND_FILE_CHUNK = 0x02

CHUNK_SIZE = 256 * 1024          # 256 КиБ — с запасом под ~1 МиБ websockets max_size
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ: получатель буферизует файл в памяти целиком
TRANSFER_ID_LEN = 16

# Расширения изображений — для инлайн-превью в чате (ChatView). Зеркалит
# mys_centralized.media.IMAGE_EXTS, но без импорта оттуда: режимы (P2P/«Центр»)
# развязаны, несмотря на похожие константы (см. mys_centralized/media.py).
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "tif"}


def kind_for_filename(filename: str) -> str:
    """``"image"`` для расширений из ``IMAGE_EXTS`` (инлайн-превью), иначе ``"file"``."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return "image" if ext in IMAGE_EXTS else "file"

_META_FIXED = TRANSFER_ID_LEN + 8 + 4 + 4 + 32  # transfer_id+total_size+chunk_size+chunk_count+sha256


@dataclass
class FileMeta:
    transfer_id: bytes
    total_size: int
    chunk_size: int
    chunk_count: int
    sha256: bytes
    mime_type: str
    filename: str


@dataclass
class FileChunk:
    transfer_id: bytes
    index: int
    data: bytes


def _put_var16(buf: bytearray, chunk: bytes) -> None:
    buf += len(chunk).to_bytes(2, "big")
    buf += chunk


def _get_var16(mv: memoryview, pos: int) -> tuple[bytes, int]:
    if pos + 2 > len(mv):
        raise TransportError("усечённое поле переменной длины (u16)")
    n = int.from_bytes(mv[pos:pos + 2], "big")
    pos += 2
    if pos + n > len(mv):
        raise TransportError("поле переменной длины выходит за payload")
    return bytes(mv[pos:pos + n]), pos + n


def _put_var8(buf: bytearray, chunk: bytes) -> None:
    buf += len(chunk).to_bytes(1, "big")
    buf += chunk


def _get_var8(mv: memoryview, pos: int) -> tuple[bytes, int]:
    if pos + 1 > len(mv):
        raise TransportError("усечённое поле переменной длины (u8)")
    n = mv[pos]
    pos += 1
    if pos + n > len(mv):
        raise TransportError("поле переменной длины выходит за payload")
    return bytes(mv[pos:pos + n]), pos + n


def encode_file_meta(meta: FileMeta) -> bytes:
    if len(meta.transfer_id) != TRANSFER_ID_LEN:
        raise ValueError(f"transfer_id должен быть {TRANSFER_ID_LEN} байт")
    if len(meta.sha256) != 32:
        raise ValueError("sha256 должен быть 32 байта")
    buf = bytearray()
    buf += meta.transfer_id
    buf += meta.total_size.to_bytes(8, "big")
    buf += meta.chunk_size.to_bytes(4, "big")
    buf += meta.chunk_count.to_bytes(4, "big")
    buf += meta.sha256
    _put_var8(buf, meta.mime_type.encode("utf-8"))
    _put_var16(buf, meta.filename.encode("utf-8"))
    return bytes(buf)


def decode_file_meta(buf: bytes) -> FileMeta:
    if len(buf) < _META_FIXED:
        raise TransportError("усечённый заголовок FILE_META")
    mv = memoryview(buf)
    pos = 0
    transfer_id = bytes(mv[pos:pos + TRANSFER_ID_LEN]); pos += TRANSFER_ID_LEN
    total_size = int.from_bytes(mv[pos:pos + 8], "big"); pos += 8
    chunk_size = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
    chunk_count = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
    sha256 = bytes(mv[pos:pos + 32]); pos += 32
    mime_raw, pos = _get_var8(mv, pos)
    filename_raw, pos = _get_var16(mv, pos)
    return FileMeta(
        transfer_id=transfer_id,
        total_size=total_size,
        chunk_size=chunk_size,
        chunk_count=chunk_count,
        sha256=sha256,
        mime_type=mime_raw.decode("utf-8", "replace"),
        filename=filename_raw.decode("utf-8", "replace"),
    )


def encode_file_chunk(chunk: FileChunk) -> bytes:
    if len(chunk.transfer_id) != TRANSFER_ID_LEN:
        raise ValueError(f"transfer_id должен быть {TRANSFER_ID_LEN} байт")
    buf = bytearray()
    buf += chunk.transfer_id
    buf += chunk.index.to_bytes(4, "big")
    buf += chunk.data
    return bytes(buf)


def decode_file_chunk(buf: bytes) -> FileChunk:
    if len(buf) < TRANSFER_ID_LEN + 4:
        raise TransportError("усечённый заголовок FILE_CHUNK")
    mv = memoryview(buf)
    transfer_id = bytes(mv[:TRANSFER_ID_LEN])
    index = int.from_bytes(mv[TRANSFER_ID_LEN:TRANSFER_ID_LEN + 4], "big")
    data = bytes(mv[TRANSFER_ID_LEN + 4:])
    return FileChunk(transfer_id=transfer_id, index=index, data=data)


def split_chunks(data: bytes, chunk_size: int | None = None) -> list[bytes]:
    """Режет ``data`` на чанки по ``chunk_size`` (по умолчанию — модульный
    ``CHUNK_SIZE``, читаемый на момент вызова, а не привязанный к сигнатуре, —
    так тесты/вызывающий код могут переопределить ``filetransfer.CHUNK_SIZE``
    без передачи параметра явно)."""
    if not data:
        return []
    size = chunk_size if chunk_size is not None else CHUNK_SIZE
    return [data[i:i + size] for i in range(0, len(data), size)]


def validate_meta(meta: FileMeta) -> None:
    if meta.total_size > MAX_FILE_SIZE:
        raise ValueError(f"файл превышает лимит {MAX_FILE_SIZE} байт")
    if meta.chunk_size <= 0:
        raise ValueError("chunk_size должен быть положительным")
    expected = math.ceil(meta.total_size / meta.chunk_size) if meta.total_size else 0
    if meta.chunk_count != expected:
        raise ValueError(
            f"chunk_count={meta.chunk_count} не соответствует ожидаемому {expected}"
        )
