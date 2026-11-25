import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.signals import Signal, SignalError, demo_signal

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


def settings(chat=CHAT):
    return Settings(bot_token="x", chat_id=chat, webhook_secret=SECRET, public_url="https://bot.example.com",
                    vest_url="https://next.vestmarkets.com/trade/GC-PERP", signal_ttl_min=15,
                    display_tz="Asia/Tashkent", execution_mode="manual")


# Pine v0.8 yuboradigan formatdagi xabar
PINE_PAYLOAD = {
    "v": 1, "symbol": "XAUUSD", "tf_sec": 300, "side": "SELL", "entry": 3543.21, "sl": 3560.87, "tp": 3518.49,
    "qty": 2.83, "risk_usd": 50, "rr": 1.4, "time": 1795598700000,
    "o": [3550 + i * 0.1 for i in range(12)], "h": [3552 + i * 0.1 for i in range(12)],
    "l": [3548 + i * 0.1 for i in range(12)], "c": [3549 + i * 0.1 for i in range(12)],
}


@pytest.fixture()
def env():
    tg = FakeTelegram()
    app = create_app(settings(), tg)
    with TestClient(app) as client:
        yield client, tg, app


def tg_headers(app):
    return {"X-Telegram-Bot-Api-Secret-Token": app.state.bot.settings.telegram_secret_token}


def press(client, app, data, chat=CHAT):
    upd = {"callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": int(chat)}, "message_id": 1}}}
    return client.post("/telegram", json=upd, headers=tg_headers(app))


def test_startup_sets_webhook(env):
    _, tg, _ = env
    assert tg.last("set_webhook")["url"] == "https://bot.example.com/telegram"


def test_tradingview_wrong_secret(env):
    client, tg, _ = env
    r = client.post("/tv/wrong", content=json.dumps(PINE_PAYLOAD))
    assert r.status_code == 403
    assert "send_photo" not in tg.names()


def test_signal_sent_with_chart_and_buttons(env):
    client, tg, _ = env
    r = client.post("/tv/" + SECRET, content=json.dumps(PINE_PAYLOAD), headers={"content-type": "text/plain"})
    assert r.status_code == 200 and r.json()["ok"]
    call = tg.last("send_photo")
    assert call["photo"][:8] == b"\x89PNG\r\n\x1a\n"
    assert "SELL signal" in call["caption"] and "3,543.21" in call["caption"] and "2.83 oz" in call["caption"]
    buttons = [b.get("callback_data") or b.get("url") for row in call["reply_markup"]["inline_keyboard"] for b in row]
    sid = r.json()["id"]
    assert f"b:{sid}" in buttons and f"s:{sid}" in buttons and f"x:{sid}" in buttons


def test_invalid_signal_rejected(env):
    client, _, _ = env
    bad = dict(PINE_PAYLOAD, side="BUY")  # BUY uchun SL kirishdan yuqorida — noto'g'ri
    r = client.post("/tv/" + SECRET, content=json.dumps(bad))
    assert r.status_code == 400


def test_sell_press_sends_ticket_and_locks(env):
    client, tg, app = env
    sid = client.post("/tv/" + SECRET, content=json.dumps(PINE_PAYLOAD)).json()["id"]
    assert press(client, app, f"s:{sid}").status_code == 200
    ticket = tg.last("send_message")["text"]
    assert "SELL — Vest GC-PERP" in ticket and "17.66" in ticket and "24.72" in ticket
    assert "Tanlandi: SELL" in tg.last("edit_caption")["caption"]
    press(client, app, f"b:{sid}")  # ikkinchi bosish qabul qilinmaydi
    assert "qaror qabul qilingan" in tg.last("answer_callback")["text"]


def test_opposite_side_warns(env):
    client, tg, app = env
    sid = client.post("/tv/" + SECRET, content=json.dumps(PINE_PAYLOAD)).json()["id"]
    press(client, app, f"b:{sid}")
    ticket = tg.last("send_message")["text"]
    assert "Signal <b>SELL</b> edi" in ticket and "pastda" in ticket


def test_skip(env):
    client, tg, app = env
    sid = client.post("/tv/" + SECRET, content=json.dumps(PINE_PAYLOAD)).json()["id"]
    press(client, app, f"x:{sid}")
    assert "O'tkazib yuborildi" in tg.last("edit_caption")["caption"]
    assert not any(c[0] == "send_message" for c in tg.calls)


def test_stranger_cannot_press(env):
    client, tg, app = env
    sid = client.post("/tv/" + SECRET, content=json.dumps(PINE_PAYLOAD)).json()["id"]
    press(client, app, f"s:{sid}", chat="999")
    assert tg.last("answer_callback")["text"] == "Ruxsat yo'q"
    assert app.state.bot.signals[sid].decision is None


def test_telegram_wrong_token(env):
    client, _, _ = env
    r = client.post("/telegram", json={"message": {"chat": {"id": 1}, "text": "/start"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": "bad"})
    assert r.status_code == 403


def test_start_shows_chat_id_for_unknown_chat():
    tg = FakeTelegram()
    app = create_app(settings(chat=None), tg)
    with TestClient(app) as client:
        client.post("/telegram", json={"message": {"chat": {"id": 555}, "text": "/start"}}, headers=tg_headers(app))
    assert "555" in tg.last("send_message")["text"]


def test_test_command_sends_demo(env):
    client, tg, app = env
    client.post("/telegram", json={"message": {"chat": {"id": int(CHAT)}, "text": "/test"}}, headers=tg_headers(app))
    assert "SELL signal" in tg.last("send_photo")["caption"]


def test_signal_validation():
    with pytest.raises(SignalError):
        Signal.from_payload({"side": "HOLD", "entry": 1, "sl": 0, "tp": 2})
    s = demo_signal()
    assert s.tp < s.entry < s.sl
