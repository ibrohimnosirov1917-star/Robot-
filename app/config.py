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
    signal_ttl_min: int = 15
    display_tz: str = "Asia/Tashkent"
    # Ijro rejimi: "dry" — bitim ochilmaydi, faqat nima qilinishi ko'rsatiladi; "live" — Tradovate'da ochiladi
    execution_mode: str = "dry"
    # Risk va hajm (MGC: 1 kontrakt = 10 oz, $1 harakat = $10)
    risk_usd: float = 250.0
    point_value: float = 10.0
    tick_size: float = 0.1
    max_contracts: int = 5
    max_trades_per_day: int = 5
    # Ruxsat bosilganda narx kirishdan SL masofasining shuncha qismidan ko'p qochgan bo'lsa — bitim ochilmaydi
    max_drift_frac: float = 0.3
    # Tradovate (Tradeify bergan login)
    tradovate_url: str = "https://trader.tradovate.com"
    tradovate_user: str = ""
    tradovate_pass: str = ""
    tradovate_account: str = ""  # hisob nomi yoki raqami (tekshirish uchun), masalan "TDFY..."
    tradovate_symbol: str = ""  # bo'sh bo'lsa joriy MGC kontrakti avtomatik tanlanadi (masalan MGCG7)
    session_dir: str = "/data"
    tradingview_url: str = "https://www.tradingview.com/chart/?symbol=COMEX%3AMGC1%21"
    # Eslatmalar: "2026-12-25=Matn; 2026-12-20=Boshqa matn" — bot 7, 3, 1 va 0 kun qolganda Telegram'ga yozadi
    reminders: str = ""

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


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_settings() -> Settings:
    return Settings(
        bot_token=_env("TELEGRAM_BOT_TOKEN"),
        chat_id=(_env("TELEGRAM_CHAT_ID") or None),
        webhook_secret=_env("WEBHOOK_SECRET"),
        public_url=_public_url(),
        signal_ttl_min=int(_env("SIGNAL_TTL_MIN", "15")),
        display_tz=_env("DISPLAY_TZ", "Asia/Tashkent"),
        execution_mode=_env("EXECUTION_MODE", "dry").lower(),
        risk_usd=float(_env("RISK_USD", "250")),
        point_value=float(_env("POINT_VALUE", "10")),
        tick_size=float(_env("TICK_SIZE", "0.1")),
        max_contracts=int(_env("MAX_CONTRACTS", "5")),
        max_trades_per_day=int(_env("MAX_TRADES_PER_DAY", "5")),
        max_drift_frac=float(_env("MAX_DRIFT_FRAC", "0.3")),
        tradovate_url=_env("TRADOVATE_URL", "https://trader.tradovate.com").rstrip("/"),
        tradovate_user=_env("TRADOVATE_USERNAME"),
        tradovate_pass=_env("TRADOVATE_PASSWORD"),
        tradovate_account=_env("TRADOVATE_ACCOUNT"),
        tradovate_symbol=_env("TRADOVATE_SYMBOL").upper(),
        session_dir=_env("SESSION_DIR", "/data"),
        reminders=_env("REMINDERS"),
        tradingview_url=_env("TRADINGVIEW_URL", "https://www.tradingview.com/chart/?symbol=COMEX%3AMGC1%21"),
    )
