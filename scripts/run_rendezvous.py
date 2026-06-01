#!/usr/bin/env python3
"""Запуск встроенного rendezvous-сервера на сети для LAN-проверки P2P.

Один из компьютеров (или любой в той же подсети) запускает этот скрипт; обе
машины вписывают напечатанный URL в поле «Rendezvous:» диалога фразы.

Пример:
    LD_LIBRARY_PATH=<libsodium_dir> .venv/bin/python scripts/run_rendezvous.py --port 8765
"""

import argparse
import asyncio
import socket

from mys_decentralized import RendezvousServer


def _lan_ip() -> str:
    """Локальный IP в сторону внешней сети (без реальной отправки пакетов)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def _main(host: str, port: int) -> None:
    server = RendezvousServer()
    bound_host, bound_port = await server.start(host, port)
    lan = _lan_ip()
    print(f"Rendezvous слушает на {bound_host}:{bound_port}")
    print(f"Вписать на обеих машинах:  ws://{lan}:{bound_port}/p2p")
    print("Ctrl-C для остановки.")
    try:
        await asyncio.Future()  # работать до прерывания
    finally:
        await server.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="LAN rendezvous для P2P-проверки")
    ap.add_argument("--host", default="0.0.0.0", help="адрес бинда (умолч. 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8765, help="порт (умолч. 8765)")
    args = ap.parse_args()
    try:
        asyncio.run(_main(args.host, args.port))
    except KeyboardInterrupt:
        pass
