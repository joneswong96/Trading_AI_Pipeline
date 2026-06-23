"""Step 5：Telegram push（sendMessage 已 wire；Phase 1 完成 TODO）。

push 文字（+ 將來 marked 截圖）。真 send 要 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID（.env）。
未有 token 前 `enabled()` False，caller graceful skip、唔會炒車。
"""
from __future__ import annotations

import os


class TelegramPublisher:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def push(self, text: str, image_path: str | None = None) -> None:
        if not self.enabled():
            raise NotImplementedError(
                "Telegram 未配（缺 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID）")
        # Phase 1 wired：Bot API sendMessage(chat_id, text)。
        # image_path（sendPhoto + caption）留待 M1。
        import requests
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        resp = requests.post(
            url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
        resp.raise_for_status()
