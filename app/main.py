"""Salom FVG — Telegram signal bot (Tradeify / Tradovate).

TradingView alert (webhook)  ──▶  POST /tv/<WEBHOOK_SECRET>  ──▶  Telegram: rasm + [Ruxsat] [O'tkazib yuborish]
Telegram tugmalari (webhook) ──▶  POST /telegram             ──▶  Ruxsat bo'lsa — bot bitimni o'zi ochadi
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request

from .chart import render_chart
from .config import Settings, load_settings
from .executor import ExecutionResult, OrderRequest, make_executor
from .signals import Signal, SignalError, _tz, decision_line, demo_signal, is_futures_symbol, signal_caption
from .sizing import Plan, front_month, plan_size, round_tick
from .telegram import Telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")
# httpx so'rov URL'ini (ichida bot tokeni bor) logga yozmasin
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

MAX_SIGNALS = 300
CODE_WAIT_SEC = 300
_CODE_RE = re.compile(r"^(?:/kod\s+)?([A-Za-z0-9]{4,10})$")


class State:
    def __init__(self, settings: Settings, tg: Telegram):
        self.settings = settings
        self.tg = tg
        self.executor = make_executor(settings, self.ask_code)
        self.signals: OrderedDict[str, Signal] = OrderedDict()
        self.messages: dict[str, tuple] = {}  # signal id -> (chat_id, message_id, caption, is_photo)
        self.trades_by_day: dict[str, int] = {}
        self.code_future: asyncio.Future | None = None
        self.run_inline = False  # testlarda ijroni fon vazifasiga chiqarmaslik uchun
        self.tasks: set[asyncio.Task] = set()

    def remember(self, sig: Signal) -> None:
        self.signals[sig.id] = sig
        while len(self.signals) > MAX_SIGNALS:
            old, _ = self.signals.popitem(last=False)
            self.messages.pop(old, None)

    def plan(self, sig: Signal) -> Plan:
        s = self.settings
        return plan_size(sig.sl_dist, s.risk_usd, s.point_value, s.max_contracts)

    def today(self) -> str:
        return datetime.now(tz=_tz(self.settings.display_tz)).strftime("%Y-%m-%d")

    def trades_today(self) -> int:
        return self.trades_by_day.get(self.today(), 0)

    def contract(self) -> str:
        return self.settings.tradovate_symbol or front_month("MGC")

    async def ask_code(self, prompt: str) -> str | None:
        """Tradovate bir martalik kod so'rasa — Telegram orqali sizdan so'raymiz."""
        if self.code_future and not self.code_future.done():
            self.code_future.cancel()
        self.code_future = asyncio.get_running_loop().create_future()
        await self.tg.send_message(self.settings.chat_id, prompt)
        try:
            return await asyncio.wait_for(self.code_future, CODE_WAIT_SEC)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None
        finally:
            self.code_future = None

    def spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def tv_button(s: Settings) -> dict:
    return {"text": "📈 TradingView", "url": s.tradingview_url}


def signal_keyboard(sig: Signal, plan: Plan, s: Settings) -> dict:
    icon = "🟢" if sig.side == "BUY" else "🔴"
    return {"inline_keyboard": [
        [{"text": f"{icon} Ruxsat: {sig.side} {plan.contracts} MGC", "callback_data": f"a:{sig.id}"}],
        [{"text": "⏭ O'tkazib yuborish", "callback_data": f"x:{sig.id}"}, tv_button(s)],
    ]}


def after_keyboard(s: Settings) -> dict:
    return {"inline_keyboard": [[tv_button(s)]]}


async def publish_signal(state: State, sig: Signal) -> dict:
    s = state.settings
    if not s.chat_id:
        raise HTTPException(503, "TELEGRAM_CHAT_ID sozlanmagan")
    state.remember(sig)
    plan = state.plan(sig)
    caption = signal_caption(sig, s.display_tz, plan)
    kb = signal_keyboard(sig, plan, s)
    png = render_chart(sig, s.display_tz)
    if png:
        res = await state.tg.send_photo(s.chat_id, png, caption, kb)
    else:
        res = await state.tg.send_message(s.chat_id, caption, kb)
    if res.get("ok"):
        state.messages[sig.id] = (s.chat_id, res["result"]["message_id"], caption, bool(png))
    log.info("Signal %s %s yuborildi (ok=%s)", sig.id, sig.side, res.get("ok"))
    return res


async def send_result(state: State, chat_id, result: ExecutionResult) -> None:
    if result.screenshot:
        await state.tg.send_photo(chat_id, result.screenshot, result.text[:1000])
    else:
        await state.tg.send_message(chat_id, result.text)


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
        await state.executor.close()

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


async def _run_or_spawn(state: State, coro) -> None:
    # Bitim ochish (login, kod kutish) uzoq davom etishi mumkin — Telegram javobini ushlab turmaymiz
    if state.run_inline:
        await coro
    else:
        state.spawn(coro)


async def handle_message(state: State, msg: dict) -> None:
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    cmd = text.split("@")[0]
    tg, s = state.tg, state.settings
    if cmd.startswith("/start"):
        if _allowed(state, chat_id):
            await tg.send_message(chat_id, "✅ Bot ishlayapti. Setup chiqqanda signal shu yerga keladi.\n/test — namunaviy signal")
        else:
            await tg.send_message(chat_id, f"Sizning chat ID: <code>{chat_id}</code>\n\nUni Railway'da <b>TELEGRAM_CHAT_ID</b> o'zgaruvchisiga kiriting.")
        return
    if not _allowed(state, chat_id):
        return  # begona foydalanuvchilarga javob bermaymiz

    m = _CODE_RE.match(text)
    if m and state.code_future is not None and not state.code_future.done():
        state.code_future.set_result(m.group(1))
        await tg.send_message(chat_id, "🔐 Kod qabul qilindi, kiritilmoqda…")
        return

    if cmd.startswith("/test"):
        await publish_signal(state, demo_signal())
    elif cmd.startswith("/status"):
        lines = [
            "✅ Bot ishlayapti",
            f"Rejim: {await state.executor.describe()}",
            f"Kontrakt: {state.contract()} · risk ${s.risk_usd:,.0f} gacha · maks {s.max_contracts} kontrakt",
            f"Bugungi bitimlar: {state.trades_today()} / {s.max_trades_per_day}",
        ]
        await tg.send_message(chat_id, "\n".join(lines))
    elif cmd.startswith("/login"):
        await tg.send_message(chat_id, "⏳ Tradovate'ga ulanmoqda…")
        await _run_or_spawn(state, _login(state, chat_id))
    elif cmd.startswith("/screen"):
        shot = await state.executor.screenshot()
        if shot:
            await tg.send_photo(chat_id, shot, "📸 Tradovate oynasi hozir")
        else:
            await tg.send_message(chat_id, "Brauzer ochiq emas (TEST rejimi yoki hali /login qilinmagan).")
    elif cmd.startswith("/flat"):
        await tg.send_message(chat_id, "⚠️ Barcha ochiq pozitsiya va buyurtmalarni yopaymi?",
                              {"inline_keyboard": [[{"text": "Ha, hammasini yopish", "callback_data": "f:yes"},
                                                    {"text": "Yo'q", "callback_data": "f:no"}]]})


async def _login(state: State, chat_id) -> None:
    await send_result(state, chat_id, await state.executor.login())


async def _execute(state: State, chat_id, req: OrderRequest) -> None:
    result = await state.executor.execute(req)
    if result.executed:
        day = state.today()
        state.trades_by_day[day] = state.trades_by_day.get(day, 0) + 1
    await send_result(state, chat_id, result)
    log.info("Signal %s: ijro ok=%s executed=%s", req.signal_id, result.ok, result.executed)


async def _flatten(state: State, chat_id) -> None:
    await send_result(state, chat_id, await state.executor.flatten())


def build_order(state: State, sig: Signal, plan: Plan) -> OrderRequest:
    s = state.settings
    return OrderRequest(
        signal_id=sig.id, side=sig.side, contracts=plan.contracts, entry=sig.entry,
        sl=round_tick(sig.sl, s.tick_size), tp=round_tick(sig.tp, s.tick_size), symbol=state.contract(),
        max_drift=s.max_drift_frac * sig.sl_dist,
    )


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

    if action == "f":
        if sid == "yes":
            await tg.answer_callback(cq["id"], "Yopilmoqda…")
            await _run_or_spawn(state, _flatten(state, chat_id))
        else:
            await tg.answer_callback(cq["id"], "Bekor qilindi")
        return

    sig = state.signals.get(sid)
    if sig is None:
        await tg.answer_callback(cq["id"], "Signal topilmadi (server qayta ishga tushgan bo'lishi mumkin)", alert=True)
        return
    if sig.decision:
        await tg.answer_callback(cq["id"], f"Bu signal bo'yicha qaror qabul qilingan: {sig.decision}")
        return
    if action not in ("a", "x"):
        await tg.answer_callback(cq["id"])
        return

    plan = state.plan(sig)
    if action == "a":
        problem = None
        if sig.age_min() > s.signal_ttl_min:
            problem = f"Signal {sig.age_min():.0f} daqiqa oldin chiqqan — eskirgan, bitim ochilmaydi."
        elif state.trades_today() >= s.max_trades_per_day:
            problem = f"Bugungi limit tugadi ({s.max_trades_per_day} ta bitim)."
        elif state.executor.live and not is_futures_symbol(sig.symbol):
            problem = "Signal MGC1! grafigidan emas — narxlar Tradovate'ga to'g'ri kelmaydi."
        if problem:
            await tg.answer_callback(cq["id"], problem, alert=True)
            return

    choice = sig.side if action == "a" else "SKIP"
    sig.decision = choice
    await tg.answer_callback(cq["id"], "O'tkazib yuborildi" if choice == "SKIP" else "Ruxsat berildi — bitim ochilmoqda…")

    stored = state.messages.get(sid)
    if stored:
        m_chat, m_id, caption, is_photo = stored
        new_caption = caption.replace("Bitimga ruxsat berasizmi? 👇", "").rstrip() + decision_line(choice, s.display_tz)
        edit = tg.edit_caption if is_photo else tg.edit_text
        await edit(m_chat, m_id, new_caption, after_keyboard(s))

    if choice != "SKIP":
        await _run_or_spawn(state, _execute(state, chat_id, build_order(state, sig, plan)))
    log.info("Signal %s: qaror %s", sid, choice)


app = create_app()
