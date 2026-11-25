"""Sozlamalar muhit o'zgaruvchilaridan (Railway → Variables) o'qiladi."""

import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    chat_id: str | None
    webhook_secret: str
    public_url: str | None
    vest_url: str
    signal_ttl_min: int
    display_tz: str
    execution_mode: str

    @property
    def telegram_secret_token(self) -> str:
        # Telegram faqat A-Z a-z 0-9 _ - belgilariga ruxsat beradi, shuning uchun hash ishlatamiz
        return hashlib.sha256(("tg:" + self.webhook_secret).encode()).hexdigest()


def _public_url() -> str | None:
    url = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    if url:
        return url
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{domain}" if domain else None


def load_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=(os.getenv("TELEGRAM_CHAT_ID", "").strip() or None),
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
        public_url=_public_url(),
        vest_url=os.getenv("VEST_URL", "https://next.vestmarkets.com/trade/GC-PERP").strip(),
        signal_ttl_min=int(os.getenv("SIGNAL_TTL_MIN", "15")),
        display_tz=os.getenv("DISPLAY_TZ", "Asia/Tashkent").strip(),
        execution_mode=os.getenv("EXECUTION_MODE", "manual").strip().lower(),
    )
