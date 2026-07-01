"""Тесты кодека файлового содержимого (kind-тег + META/CHUNK) — вне сессии/сети."""

import math

import pytest

from mys_decentralized import filetransfer as ft
from mys_decentralized.errors import TransportError


def _meta(**over):
    base = dict(
        transfer_id=b"t" * ft.TRANSFER_ID_LEN,
        total_size=1000,
        chunk_size=ft.CHUNK_SIZE,
        chunk_count=math.ceil(1000 / ft.CHUNK_SIZE),
        sha256=b"s" * 32,
        mime_type="text/plain",
        filename="report.txt",
    )
    base.update(over)
    return ft.FileMeta(**base)


# --- FILE_META round-trip -----------------------------------------------------

def test_file_meta_round_trip():
    meta = _meta()
    out = ft.decode_file_meta(ft.encode_file_meta(meta))
    assert out == meta


def test_file_meta_round_trip_unicode_filename_and_mime():
    meta = _meta(filename="фото — отпуск 🌴.png", mime_type="image/png")
    out = ft.decode_file_meta(ft.encode_file_meta(meta))
    assert out == meta


def test_file_meta_round_trip_empty_filename():
    meta = _meta(filename="", mime_type="")
    out = ft.decode_file_meta(ft.encode_file_meta(meta))
    assert out == meta


def test_file_meta_rejects_truncated_header():
    with pytest.raises(TransportError):
        ft.decode_file_meta(b"\x00" * (ft._META_FIXED - 1))


def test_file_meta_rejects_truncated_variable_field():
    encoded = ft.encode_file_meta(_meta())
    with pytest.raises(TransportError):
        ft.decode_file_meta(encoded[:-1])


def test_file_meta_encode_rejects_bad_transfer_id_len():
    with pytest.raises(ValueError):
        ft.encode_file_meta(_meta(transfer_id=b"short"))


# --- FILE_CHUNK round-trip -----------------------------------------------------

def test_file_chunk_round_trip():
    chunk = ft.FileChunk(transfer_id=b"t" * ft.TRANSFER_ID_LEN, index=7, data=b"payload-bytes")
    out = ft.decode_file_chunk(ft.encode_file_chunk(chunk))
    assert out == chunk


def test_file_chunk_round_trip_empty_data():
    chunk = ft.FileChunk(transfer_id=b"t" * ft.TRANSFER_ID_LEN, index=0, data=b"")
    out = ft.decode_file_chunk(ft.encode_file_chunk(chunk))
    assert out == chunk


def test_file_chunk_rejects_truncated_header():
    with pytest.raises(TransportError):
        ft.decode_file_chunk(b"\x00" * (ft.TRANSFER_ID_LEN + 3))


def test_file_chunk_encode_rejects_bad_transfer_id_len():
    with pytest.raises(ValueError):
        ft.encode_file_chunk(ft.FileChunk(transfer_id=b"short", index=0, data=b""))


# --- split_chunks --------------------------------------------------------------

def test_split_chunks_empty():
    assert ft.split_chunks(b"") == []


def test_split_chunks_smaller_than_chunk_size():
    data = b"x" * 10
    assert ft.split_chunks(data, chunk_size=100) == [data]


def test_split_chunks_exact_multiple():
    data = b"x" * 20
    chunks = ft.split_chunks(data, chunk_size=5)
    assert chunks == [b"x" * 5] * 4


def test_split_chunks_one_byte_over():
    data = b"x" * 21
    chunks = ft.split_chunks(data, chunk_size=5)
    assert len(chunks) == 5
    assert b"".join(chunks) == data
    assert chunks[-1] == b"x"


# --- validate_meta ---------------------------------------------------------------

def test_validate_meta_accepts_consistent_meta():
    ft.validate_meta(_meta(total_size=1000, chunk_size=ft.CHUNK_SIZE, chunk_count=1))


def test_validate_meta_accepts_zero_size_zero_chunks():
    ft.validate_meta(_meta(total_size=0, chunk_size=ft.CHUNK_SIZE, chunk_count=0))


def test_validate_meta_rejects_oversized_file():
    with pytest.raises(ValueError):
        ft.validate_meta(_meta(total_size=ft.MAX_FILE_SIZE + 1, chunk_count=1))


def test_validate_meta_rejects_too_few_chunks():
    with pytest.raises(ValueError):
        ft.validate_meta(_meta(total_size=1000, chunk_size=100, chunk_count=1))  # нужно 10


def test_validate_meta_rejects_too_many_chunks():
    with pytest.raises(ValueError):
        ft.validate_meta(_meta(total_size=1000, chunk_size=100, chunk_count=99))


def test_validate_meta_rejects_nonpositive_chunk_size():
    with pytest.raises(ValueError):
        ft.validate_meta(_meta(chunk_size=0, chunk_count=0))
