import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.executor import ExecutionResult, OrderRequest
from app.main import create_app
from app.signals import Signal, SignalError, demo_signal
from app.sizing import front_month, plan_size, round_tick
from app.tradovate import check_price, fill_template, parse_price

CHAT = "111"
SECRET = "s3cret-value"


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self._mid = 100

    async def _ok(self, name, **kw):
        self.calls.append((name, kw))
        self._mid += 1
        return {"ok": True, "result": {"message_id": self._mid}}

    async def send_message(self, chat_id, text, reply_markup=None):
        return await self._ok("send_message", chat_id=chat_id, text=text, reply_markup=reply_markup)

    async def send_photo(self, chat_id, photo, caption, reply_markup=None):
        return await self._ok("send_photo", chat_id=chat_id, photo=photo, caption=caption, reply_markup=reply_markup)

    async def send_document(self, chat_id, data, filename, caption=""):
        return await self._ok("send_document", chat_id=chat_id, data=data, filename=filename, caption=caption)

    async def edit_caption(self, chat_id, message_id, caption, reply_markup=None):
        return await self._ok("edit_caption", chat_id=chat_id, message_id=message_id, caption=caption, reply_markup=reply_markup)

    async def edit_text(self, chat_id, message_id, text, reply_markup=None):
        return await self._ok("edit_text", chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)

    async def answer_callback(self, callback_id, text="", alert=False):
        return await self._ok("answer_callback", text=text, alert=alert)

    async def set_webhook(self, url, secret_token):
        return await self._ok("set_webhook", url=url)

    async def set_commands(self):
        return await self._ok("set_commands")

    def names(self):
        return [c[0] for c in self.calls]

    def last(self, name):
        return [c for c in self.calls if c[0] == name][-1][1]


class FakeLive:
    """Haqiqiy brauzersiz 'live' ijrochi — main.py oqimini tekshirish uchun."""
    name = "live"
    live = True

    def __init__(self):
        self.orders = []

    async def execute(self, req):
        self.orders.append(req)
        return ExecutionResult(ok=True, executed=True, text="✅ Bitim ochildi")

    async def describe(self):
        return "fake"

    async def screenshot(self):
        return b"\x89PNG-tradovate"

    async def close(self):
        pass


def settings(**kw):
    base = dict(bot_token="x", chat_id=CHAT, webhook_secret=SECRET, public_url="https://bot.example.com",
                tradovate_symbol="MGCG7")
    base.update(kw)
    return Settings(**base)


# Pine v0.8 yuboradigan formatdagi xabar (MGC1! grafigidan)
PINE_PAYLOAD = {
    "v": 1, "symbol": "MGC1!", "tf_sec": 300, "side": "SELL", "entry": 3543.21, "sl": 3560.87, "tp": 3518.49,
    "qty": 0.28, "risk_usd": 250, "rr": 1.4, "time": 1795598700000,
    "o": [3550 + i * 0.1 for i in range(12)], "h": [3552 + i * 0.1 for i in range(12)],
    "l": [3548 + i * 0.1 for i in range(12)], "c": [3549 + i * 0.1 for i in range(12)],
}


@pytest.fixture()
def env(tmp_path):
    tg = FakeTelegram()
    app = create_app(settings(session_dir=str(tmp_path)), tg)
    with TestClient(app) as client:
        app.state.bot.run_inline = True
        yield client, tg, app


def tg_headers(app):
    return {"X-Telegram-Bot-Api-Secret-Token": app.state.bot.settings.telegram_secret_token}


def press(client, app, data, chat=CHAT):
    upd = {"callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": int(chat)}, "message_id": 1}}}
    return client.post("/telegram", json=upd, headers=tg_headers(app))


def say(client, app, text, chat=CHAT):
    upd = {"message": {"chat": {"id": int(chat)}, "text": text}}
    return client.post("/telegram", json=upd, headers=tg_headers(app))


def post_signal(client, payload=PINE_PAYLOAD):
    return client.post("/tv/" + SECRET, content=json.dumps(payload)).json()["id"]


# ───────── hajm va kontrakt ─────────
def test_plan_size():
    assert plan_size(23.64, 250, 10, 5).contracts == 1          # 1 × $236
    p = plan_size(12, 250, 10, 5)
    assert p.contracts == 2 and p.risk_total == 240 and not p.over_risk
    p = plan_size(30, 250, 10, 5)
    assert p.contracts == 1 and p.over_risk and p.risk_total == 300
    assert plan_size(2, 250, 10, 5).contracts == 5               # maks kontrakt cheklovi


def test_front_month_and_tick():
    assert front_month("MGC", date(2026, 11, 26)) == "MGCG7"
    assert front_month("MGC", date(2026, 11, 10)) == "MGCZ6"
    assert front_month("MGC", date(2026, 12, 30)) == "MGCG7"
    assert front_month("MGC", date(2027, 1, 25)) == "MGCJ7"
    assert round_tick(3536.16, 0.1) == 3536.2


# ───────── signal xabari ─────────
def test_startup_sets_webhook(env):
    _, tg, _ = env
    assert tg.last("set_webhook")["url"] == "https://bot.example.com/telegram"


def test_tradingview_wrong_secret(env):
    client, tg, _ = env
    assert client.post("/tv/wrong", content=json.dumps(PINE_PAYLOAD)).status_code == 403
    assert "send_photo" not in tg.names()


def test_signal_sent_with_contracts_and_buttons(env):
    client, tg, _ = env
    sid = post_signal(client)
    call = tg.last("send_photo")
    assert call["photo"][:8] == b"\x89PNG\r\n\x1a\n"
    cap = call["caption"]
    assert "SELL signal" in cap and "3,543.21" in cap and "1 MGC" in cap and "$177" in cap
    assert "Vest" not in cap and "oz" not in cap
    kb = call["reply_markup"]["inline_keyboard"]
    datas = [b.get("callback_data") for row in kb for b in row]
    assert f"a:{sid}" in datas and f"x:{sid}" in datas
    assert "Ruxsat: SELL 1 MGC" in kb[0][0]["text"]
    assert not any("vest" in (b.get("url") or "") for row in kb for b in row)


def test_xauusd_signal_warns(env):
    client, tg, _ = env
    post_signal(client, dict(PINE_PAYLOAD, symbol="XAUUSD"))
    assert "MGC1!" in tg.last("send_photo")["caption"]


def test_invalid_signal_rejected(env):
    client, _, _ = env
    bad = dict(PINE_PAYLOAD, side="BUY")  # BUY uchun SL kirishdan yuqorida — noto'g'ri
    assert client.post("/tv/" + SECRET, content=json.dumps(bad)).status_code == 400


# ───────── ruxsat oqimi ─────────
def test_approve_in_dry_mode(env):
    client, tg, app = env
    sid = post_signal(client)
    assert press(client, app, f"a:{sid}").status_code == 200
    msg = tg.last("send_message")["text"]
    assert "TEST rejimi" in msg and "MGCG7" in msg and "3,560.90" in msg and "3,518.50" in msg
    assert "Ruxsat berildi: SELL" in tg.last("edit_caption")["caption"]
    # ikkinchi bosish — qayta ochilmaydi
    n = len(tg.calls)
    press(client, app, f"a:{sid}")
    assert "qaror qabul qilingan" in tg.calls[-1][1]["text"] and len(tg.calls) == n + 1


def test_skip(env):
    client, tg, app = env
    sid = post_signal(client)
    press(client, app, f"x:{sid}")
    assert "O'tkazib yuborildi" in tg.last("edit_caption")["caption"]
    assert "TEST rejimi" not in " ".join(str(c) for c in tg.calls)


def test_expired_signal_not_executed(env):
    client, tg, app = env
    sid = post_signal(client)
    app.state.bot.signals[sid].received_at = time.time() - 3600
    press(client, app, f"a:{sid}")
    last = tg.last("answer_callback")
    assert last["alert"] and "eskirgan" in last["text"]
    assert app.state.bot.signals[sid].decision is None


def test_live_flow_daily_limit_and_order(env):
    client, tg, app = env
    fake = FakeLive()
    app.state.bot.executor = fake
    for i in range(5):
        press(client, app, f"a:{post_signal(client)}")
    assert len(fake.orders) == 5
    o = fake.orders[0]
    assert (o.side, o.contracts, o.symbol, o.sl, o.tp) == ("SELL", 1, "MGCG7", 3560.9, 3518.5)
    assert abs(o.max_drift - 0.3 * 17.66) < 1e-6
    press(client, app, f"a:{post_signal(client)}")
    assert "limit" in tg.last("answer_callback")["text"] and len(fake.orders) == 5


def test_live_refuses_non_futures_symbol(env):
    client, tg, app = env
    app.state.bot.executor = FakeLive()
    press(client, app, f"a:{post_signal(client, dict(PINE_PAYLOAD, symbol='XAUUSD'))}")
    assert "MGC1!" in tg.last("answer_callback")["text"] and not app.state.bot.executor.orders


def test_status_and_stranger(env):
    client, tg, app = env
    say(client, app, "/status")
    assert "TEST" in tg.last("send_message")["text"] and "MGCG7" in tg.last("send_message")["text"]
    n = len(tg.calls)
    say(client, app, "/status", chat="999")
    assert len(tg.calls) == n


def test_demo_signal_validation():
    with pytest.raises(SignalError):
        Signal.from_payload({"side": "HOLD", "entry": 1, "sl": 0, "tp": 2})
    s = demo_signal()
    assert s.tp < s.entry < s.sl


# ───────── Tradovate yordamchi funksiyalari ─────────
REQ = OrderRequest(signal_id="x", side="BUY", contracts=2, entry=3561.9, sl=3536.2, tp=3597.9, symbol="MGCG7", max_drift=7.7)


def test_price_checks():
    assert parse_price("Last 3,561.80") == 3561.8
    assert parse_price("—") is None
    assert check_price(REQ, 3563.0) is None
    assert "qochgan" in check_price(REQ, 3575.0)
    assert "oralig'ida emas" in check_price(REQ, 3530.0)
    assert fill_template("{side_title} {qty} {symbol} {sl}", REQ) == "Buy 2 MGCG7 3536.2"


# ───────── jurnal: natija (TP/SL) ─────────
def exit_payload(**kw):
    p = {"v": 1, "event": "exit", "symbol": "MGC1!", "tf_sec": 300, "side": "SELL", "entry": 3543.21, "exit": 3518.49,
         "sl": 3560.87, "tp": 3518.49, "result": "TP", "entry_time": 1795598700000, "time": 1795598700000 + 6 * 300_000,
         "o": [3550 - i for i in range(12)], "h": [3552 - i for i in range(12)],
         "l": [3540 - i for i in range(12)], "c": [3549 - i for i in range(12)]}
    p.update(kw)
    return p


def test_exit_after_approval_sends_chart_and_records(env):
    client, tg, app = env
    sid = post_signal(client)
    press(client, app, f"a:{sid}")
    r = client.post("/tv/" + SECRET, content=json.dumps(exit_payload()))
    assert r.status_code == 200 and r.json() == {"ok": True, "id": sid, "result": "TP"}
    call = tg.last("send_photo")
    assert call["photo"][:8] == b"\x89PNG\r\n\x1a\n"
    cap = call["caption"]
    assert "TP" in cap and "+24.7 punkt" in cap and "+1.4R" in cap and "Ruxsat berilgan edi" in cap and "$+247" in cap
    t = app.state.bot.journal.trades[sid]
    assert t.result == "TP" and t.decision == "SELL" and t.executed is False


def test_exit_of_skipped_signal_and_stats(env):
    client, tg, app = env
    sid = post_signal(client)
    press(client, app, f"x:{sid}")
    client.post("/tv/" + SECRET, content=json.dumps(exit_payload(result="SL", exit=3560.87)))
    assert "o'tkazib yuborgan" in tg.last("send_photo")["caption"] and "-1.0R" in tg.last("send_photo")["caption"]
    # ikkinchi signal — ruxsat + live (soxta) ijro + TP
    app.state.bot.executor = FakeLive()
    sid2 = post_signal(client)
    press(client, app, f"a:{sid2}")
    client.post("/tv/" + SECRET, content=json.dumps(exit_payload()))
    photos = [c[1] for c in tg.calls if c[0] == "send_photo"]
    assert "Hisobda: 1 MGC" in photos[-2]["caption"] and photos[-1]["caption"] == "📸 Tradovate holati"
    say(client, app, "/stats")
    st = tg.last("send_message")["text"]
    assert "Signallar: 2" in st and "O'tkazib yuborilgan: 1 ta · TP 0 / SL 1" in st and "haqiqatan ochilgan: 1 ta · TP 1" in st
    say(client, app, "/jurnal")
    doc = tg.last("send_document")
    text = doc["data"].decode("utf-8-sig")
    assert doc["filename"] == "jurnal.csv" and text.count("\n") == 3 and "SKIP" in text and ",TP," in text


def test_journal_survives_restart(tmp_path):
    from app.journal import Journal

    tg = FakeTelegram()
    app = create_app(settings(session_dir=str(tmp_path)), tg)
    with TestClient(app) as client:
        app.state.bot.run_inline = True
        sid = post_signal(client)
        press(client, app, f"a:{sid}")
    j = Journal(str(tmp_path / "journal.jsonl"))
    assert j.trades[sid].decision == "SELL" and j.find_open("SELL", 3543.21).id == sid
    # qayta ishga tushgandan keyin ham natija mos signalga yoziladi
    app2 = create_app(settings(session_dir=str(tmp_path)), FakeTelegram())
    with TestClient(app2) as client2:
        r = client2.post("/tv/" + SECRET, content=json.dumps(exit_payload()))
        assert r.json()["id"] == sid


def test_exit_without_signal(env):
    client, tg, _ = env
    r = client.post("/tv/" + SECRET, content=json.dumps(exit_payload()))
    assert r.json()["id"] is None and "topilmadi" in tg.last("send_photo")["caption"]
