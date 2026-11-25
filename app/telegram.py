"""Telegram Bot API bilan ishlash uchun kichik klient."""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger("telegram")


class Telegram:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.client = client or httpx.AsyncClient(timeout=20)

    async def call(self, method: str, data: dict | None = None, files: dict | None = None) -> dict:
        payload = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in (data or {}).items() if v is not None}
        r = await self.client.post(f"{self.base}/{method}", data=payload, files=files)
        body = r.json()
        if not body.get("ok"):
            log.warning("Telegram %s xato: %s", method, body.get("description"))
        return body

    async def send_message(self, chat_id, text: str, reply_markup: dict | None = None) -> dict:
        return await self.call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                               "disable_web_page_preview": True, "reply_markup": reply_markup})

    async def send_photo(self, chat_id, photo: bytes, caption: str, reply_markup: dict | None = None) -> dict:
        return await self.call("sendPhoto", {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML",
                                             "reply_markup": reply_markup},
                               files={"photo": ("signal.png", photo, "image/png")})

    async def send_document(self, chat_id, data: bytes, filename: str, caption: str = "") -> dict:
        return await self.call("sendDocument", {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                               files={"document": (filename, data, "text/csv")})

    async def edit_caption(self, chat_id, message_id: int, caption: str, reply_markup: dict | None = None) -> dict:
        return await self.call("editMessageCaption", {"chat_id": chat_id, "message_id": message_id, "caption": caption,
                                                      "parse_mode": "HTML", "reply_markup": reply_markup})

    async def edit_text(self, chat_id, message_id: int, text: str, reply_markup: dict | None = None) -> dict:
        return await self.call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text,
                                                   "parse_mode": "HTML", "reply_markup": reply_markup})

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> dict:
        return await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": alert})

    async def set_webhook(self, url: str, secret_token: str) -> dict:
        return await self.call("setWebhook", {"url": url, "secret_token": secret_token,
                                              "allowed_updates": ["message", "callback_query"], "drop_pending_updates": True})

    async def set_commands(self) -> dict:
        return await self.call("setMyCommands", {"commands": [
            {"command": "start", "description": "Botni ishga tushirish va chat ID"},
            {"command": "test", "description": "Namunaviy signal yuborish"},
            {"command": "status", "description": "Bot holati va bugungi bitimlar"},
            {"command": "stats", "description": "Jurnal statistikasi (masalan /stats 30)"},
            {"command": "jurnal", "description": "Jurnalni CSV fayl qilib yuborish"},
            {"command": "eslatma", "description": "To'lov va muddatlar ro'yxati"},
            {"command": "login", "description": "Tradovate'ga ulanish (skrinshot bilan)"},
            {"command": "screen", "description": "Tradovate oynasining skrinshoti"},
            {"command": "flat", "description": "Barcha pozitsiyalarni yopish (favqulodda)"},
        ]})
