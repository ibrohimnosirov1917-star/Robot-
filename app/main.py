"""Salom FVG — Telegram signal bot.

TradingView alert (webhook)  ──▶  POST /tv/<WEBHOOK_SECRET>
Telegram tugmalari (webhook) ──▶  POST /telegram
"""

from __future__ import annotations

import hmac
import json
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from .chart import render_chart
from .config import Settings, load_settings
from .executor import make_executor
from .signals import Signal, SignalError, decision_line, demo_signal, signal_caption
from .telegram import Telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

MAX_SIGNALS = 300


class State:
    def __init__(self, settings: Settings, tg: Telegram):
        self.settings = settings
        self.tg = tg
        self.executor = make_executor(settings.execution_mode, settings.signal_ttl_min)
        self.signals: OrderedDict[str, Signal] = OrderedDict()
        self.messages: dict[str, tuple] = {}  # signal id -> (chat_id, message_id, caption)

    def remember(self, sig: Signal) -> None:
        self.signals[sig.id] = sig
        while len(self.signals) > MAX_SIGNALS:
            old, _ = self.signals.popitem(last=False)
            self.messages.pop(old, None)


def signal_keyboard(sig: Signal, vest_url: str) -> dict:
    return {"inline_keyboard": [
        [{"text": "🟢 BUY", "callback_data": f"b:{sig.id}"}, {"text": "🔴 SELL", "callback_data": f"s:{sig.id}"}],
        [{"text": "⏭ O'tkazib yuborish", "callback_data": f"x:{sig.id}"}, {"text": "🔗 Vest", "url": vest_url}],
    ]}


def vest_keyboard(vest_url: str) -> dict:
    return {"inline_keyboard": [[{"text": "🔗 Vest GC-PERP'ni ochish", "url": vest_url}]]}


async def publish_signal(state: State, sig: Signal) -> dict:
    s = state.settings
    if not s.chat_id:
        raise HTTPException(503, "TELEGRAM_CHAT_ID sozlanmagan")
    state.remember(sig)
    caption = signal_caption(sig, s.display_tz)
    kb = signal_keyboard(sig, s.vest_url)
    png = render_chart(sig, s.display_tz)
    if png:
        res = await state.tg.send_photo(s.chat_id, png, caption, kb)
    else:
        res = await state.tg.send_message(s.chat_id, caption, kb)
    if res.get("ok"):
        state.messages[sig.id] = (s.chat_id, res["result"]["message_id"], caption, bool(png))
    log.info("Signal %s %s yuborildi (ok=%s)", sig.id, sig.side, res.get("ok"))
    return res


def create_app(settings: Settings | None = None, tg: Telegram | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state: State = app.state.bot
        if not settings.bot_token or not settings.webhook_secret:
            log.error("TELEGRAM_BOT_TOKEN va WEBHOOK_SECRET o'zgaruvchilarini kiriting")
        elif settings.public_url:
            try:
                res = await state.tg.set_webhook(f"{settings.public_url}/telegram", settings.telegram_secret_token)
                log.info("Telegram webhook: %s", "o'rnatildi" if res.get("ok") else res)
                await state.tg.set_commands()
            except Exception as e:  # Telegram vaqtincha ishlamasa ham server ishga tushsin
                log.error("Telegram webhook o'rnatilmadi: %s", e)
        else:
            log.warning("PUBLIC_URL yoki RAILWAY_PUBLIC_DOMAIN yo'q — Telegram webhook o'rnatilmadi")
        yield

    app = FastAPI(title="Salom FVG signal bot", lifespan=lifespan)
    app.state.bot = State(settings, tg or Telegram(settings.bot_token))

    @app.get("/")
    async def health():
        s = settings
        return {"ok": True, "chat_id_set": bool(s.chat_id), "public_url": s.public_url,
                "mode": s.execution_mode, "signals": len(app.state.bot.signals)}

    @app.post("/tv/{secret}")
    async def tradingview(secret: str, request: Request):
        if not settings.webhook_secret or not hmac.compare_digest(secret, settings.webhook_secret):
            raise HTTPException(403, "noto'g'ri secret")
        raw = await request.body()
        try:
            payload = json.loads(raw)
            sig = Signal.from_payload(payload)
        except (json.JSONDecodeError, SignalError) as e:
            log.warning("Noto'g'ri signal: %s | %s", e, raw[:200])
            raise HTTPException(400, f"noto'g'ri signal: {e}")
        res = await publish_signal(app.state.bot, sig)
        return {"ok": bool(res.get("ok")), "id": sig.id}

    @app.post("/telegram")
    async def telegram(request: Request):
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, settings.telegram_secret_token):
            raise HTTPException(403, "noto'g'ri token")
        update = await request.json()
        state: State = app.state.bot
        if "callback_query" in update:
            await handle_callback(state, update["callback_query"])
        elif "message" in update:
            await handle_message(state, update["message"])
        return {"ok": True}

    return app


def _allowed(state: State, chat_id) -> bool:
    return state.settings.chat_id is not None and str(chat_id) == str(state.settings.chat_id)


async def handle_message(state: State, msg: dict) -> None:
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip().split("@")[0]
    tg, s = state.tg, state.settings
    if text.startswith("/start"):
        if _allowed(state, chat_id):
            await tg.send_message(chat_id, "✅ Bot ishlayapti. Setup chiqqanda signal shu yerga keladi.\n/test — namunaviy signal")
        else:
            await tg.send_message(chat_id, f"Sizning chat ID: <code>{chat_id}</code>\n\nUni Railway'da <b>TELEGRAM_CHAT_ID</b> o'zgaruvchisiga kiriting.")
        return
    if not _allowed(state, chat_id):
        return  # begona foydalanuvchilarga javob bermaymiz
    if text.startswith("/test"):
        await publish_signal(state, demo_signal())
    elif text.startswith("/status"):
        await tg.send_message(chat_id, f"✅ Ishlayapti · rejim: {s.execution_mode} · xotiradagi signallar: {len(state.signals)}")


async def handle_callback(state: State, cq: dict) -> None:
    tg, s = state.tg, state.settings
    chat_id = cq.get("message", {}).get("chat", {}).get("id")
    if not _allowed(state, chat_id):
        await tg.answer_callback(cq["id"], "Ruxsat yo'q")
        return
    try:
        action, sid = cq.get("data", "").split(":", 1)
    except ValueError:
        await tg.answer_callback(cq["id"])
        return
    sig = state.signals.get(sid)
    if sig is None:
        await tg.answer_callback(cq["id"], "Signal topilmadi (server qayta ishga tushgan bo'lishi mumkin)", alert=True)
        return
    if sig.decision:
        await tg.answer_callback(cq["id"], f"Bu signal bo'yicha qaror qabul qilingan: {sig.decision}")
        return

    choice = {"b": "BUY", "s": "SELL", "x": "SKIP"}.get(action)
    if choice is None:
        await tg.answer_callback(cq["id"])
        return
    sig.decision = choice
    await tg.answer_callback(cq["id"], "O'tkazib yuborildi" if choice == "SKIP" else f"{choice} tanlandi")

    stored = state.messages.get(sid)
    if stored:
        m_chat, m_id, caption, is_photo = stored
        new_caption = caption.replace("Bitim ochish uchun tugmani bosing 👇", "").rstrip() + decision_line(choice, s.display_tz)
        edit = tg.edit_caption if is_photo else tg.edit_text
        await edit(m_chat, m_id, new_caption, vest_keyboard(s.vest_url))

    if choice != "SKIP":
        result = await state.executor.execute(sig, choice)
        await tg.send_message(chat_id, result.text, vest_keyboard(s.vest_url))
    log.info("Signal %s: qaror %s", sid, choice)


app = create_app()
