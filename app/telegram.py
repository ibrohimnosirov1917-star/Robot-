"""Telegram Bot API bilan ishlash uchun kichik klient."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re

import httpx

log = logging.getLogger("telegram")


class Telegram:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.client = client or httpx.AsyncClient(timeout=20)

    async def call(self, method: str, data: dict | None = None, files: dict | None = None) -> dict:
        """Telegram'ga so'rov. Tarmoq xatosida 3 marta urinadi; HTML xato bo'lsa — oddiy matn bilan qayta yuboradi.
        Hech qachon exception tashlamaydi (bot ishlashda davom etishi kerak)."""
        data = dict(data or {})
        for attempt in range(3):
            payload = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in data.items() if v is not None}
            try:
                r = await self.client.post(f"{self.base}/{method}", data=payload, files=files)
                body = r.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Telegram %s tarmoq xatosi (%s-urinish): %s", method, attempt + 1, e)
                await asyncio.sleep(1 + 2 * attempt)
                continue
            if body.get("ok"):
                return body
            desc = str(body.get("description", ""))
            log.warning("Telegram %s xato: %s", method, desc)
            if "parse entities" in desc and data.get("parse_mode"):
                data.pop("parse_mode", None)
                for key in ("text", "caption"):
                    if isinstance(data.get(key), str):
                        data[key] = html.unescape(re.sub(r"<[^>]+>", "", data[key]))
                continue
            return body
        return {"ok": False, "description": "Telegram'ga yuborib bo'lmadi"}

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
            {"command": "narx", "description": "Tradovate formasini sinash (bitim ochmaydi)"},
            {"command": "login", "description": "Tradovate'ga ulanish (skrinshot bilan)"},
            {"command": "screen", "description": "Tradovate oynasining skrinshoti"},
            {"command": "flat", "description": "Barcha pozitsiyalarni yopish (favqulodda)"},
        ]})
