"""Вложения централизованного режима: лимиты, allowlist расширений, имена.

Чистые функции без сети/vault/Qt. Зеркалит серверный ``EXT_TO_MIME``
(``vsc_web/vsc_web/rooms.py``) для быстрого отказа на клиенте до сетевого
запроса — сервер остаётся источником истины и всё равно перепроверяет.
Независимый от ``mys_decentralized.filetransfer`` модуль: режимы (P2P/«Центр»)
развязаны, несмотря на похожие константы.
"""

MAX_MEDIA_SIZE = 50 * 1024 * 1024  # 50 МБ

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "tif"}

EXT_TO_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "tiff": "image/tiff", "tif": "image/tiff",
    "mp4": "video/mp4", "webm": "video/webm",
    "mov": "video/quicktime", "avi": "video/x-msvideo",
    "mp3": "audio/mpeg", "ogg": "audio/ogg",
    "wav": "audio/wav",
    "pdf": "application/pdf",
    "txt": "text/plain", "csv": "text/csv",
    "zip": "application/zip",
    "rar": "application/vnd.rar",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "appimage": "application/x-executable",
}


def ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_extension(filename: str) -> None:
    """Бросает ``ValueError`` (с русским текстом), если расширение не разрешено."""
    ext = ext_of(filename)
    if ext not in EXT_TO_MIME:
        raise ValueError(f"Расширение не разрешено: .{ext}")


def kind_for_filename(filename: str) -> str:
    return "image" if ext_of(filename) in IMAGE_EXTS else "file"


def display_name(media_ref: str) -> str:
    """Отображаемое имя из серверного ``<uuid32hex>_<original>`` — паритет с вебом."""
    _, _, rest = media_ref.partition("_")
    return rest or media_ref
