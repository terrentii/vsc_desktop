"""Best-effort зануление ключевого материала в памяти.

Ограничение: исходные `bytes` в Python иммутабельны и могут копироваться GC —
гарантия зануления не абсолютная. SecureBytes снижает время жизни ключей в
изменяемом буфере и затирает его явно.
"""


class SecureBytes:
    def __init__(self, data: bytes | bytearray):
        self._buf = bytearray(data)

    def __bytes__(self) -> bytes:
        return bytes(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    def hex(self) -> str:
        return self._buf.hex()

    def wipe(self) -> None:
        for i in range(len(self._buf)):
            self._buf[i] = 0

    def __enter__(self) -> "SecureBytes":
        return self

    def __exit__(self, *exc) -> None:
        self.wipe()
