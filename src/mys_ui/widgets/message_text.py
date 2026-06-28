"""Разбор тела сообщения на сегменты текст/код по ```-ограждениям.

Повторяет семантику серверного `render_text` (vsc_web, app.py): чётные части —
текст, нечётные — код с обрезкой ведущего/хвостового перевода строки.
"""

import re

_FENCE = re.compile(r"```([\s\S]*?)```")


def split_segments(body: str) -> list[tuple[str, str]]:
    parts = _FENCE.split(body or "")
    out: list[tuple[str, str]] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part:
                out.append(("text", part))
        else:
            code = re.sub(r"^\r?\n", "", re.sub(r"\r?\n$", "", part))
            out.append(("code", code))
    return out or [("text", "")]
