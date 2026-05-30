"""Ошибки децентрализованного модуля."""


class DecentralizedError(Exception):
    """Базовая ошибка P2P-модуля."""


class PAKEError(DecentralizedError):
    """Провал PAKE/key-confirmation: неверная фраза или попытка перехвата (MITM)."""


class RendezvousError(DecentralizedError):
    """Ошибка взаимодействия с rendezvous-сервером."""


class TransportError(DecentralizedError):
    """Ошибка транспорта (битый/неполный кадр, обрыв соединения)."""


class PeerUnavailable(DecentralizedError):
    """Пир не появился в комнате за отведённый таймаут."""
