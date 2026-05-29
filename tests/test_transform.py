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
