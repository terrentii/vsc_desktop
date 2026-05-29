"""Лента сообщений диалога."""

from PySide6.QtWidgets import QListWidget


class ChatView(QListWidget):
    def show_messages(self, messages: list[dict]) -> None:
        self.clear()
        for m in messages:
            prefix = "→ " if m["direction"] == "out" else "← "
            body = m["body"].decode("utf-8", "replace") if m["body"] is not None else ""
            self.addItem(prefix + body)
