"""TradovateBrowser'ni haqiqiy Chromium bilan, Tradovate'ga o'xshatilgan soxta sahifada sinash.

Brauzer topilmasa test o'tkazib yuboriladi. Lokal ishga tushirish:
    BROWSER_EXECUTABLE=/usr/bin/google-chrome pytest -q tests/test_browser.py
"""

import asyncio
import functools
import http.server
import os
import shutil
import threading

import pytest

from app.config import Settings
from app.executor import OrderRequest

pytest.importorskip("playwright")

MOCK = """<!doctype html><html><body>
<div id="login"><input id="name-input" type="text"><input id="password-input" type="password">
<button onclick="go('code')">Login</button></div>
<div id="code" hidden><input name="code"><button onclick="go('env')">Verify</button></div>
<div id="env" hidden><button onclick="go('trade')">Access Simulation</button></div>
<div id="trade" hidden>
  <div>Account: TDFY-DEMO-1</div>
  <span id="last-price">3,561.80</span>
  <input placeholder="Symbol"><input placeholder="Qty"><input placeholder="Stop price"><input placeholder="Target price">
  <button onclick="order('Buy')">Buy Mkt</button><button onclick="order('Sell')">Sell Mkt</button>
  <button onclick="document.getElementById('orders').textContent='FLAT'">Exit at Mkt &amp; Cxl</button>
  <div id="orders"></div>
</div>
<script>
function go(id){for(const d of ['login','code','env','trade'])document.getElementById(d).hidden=(d!==id);}
function order(side){
  const v=[...document.querySelectorAll('#trade input')].map(i=>i.value);
  if(v[2]==='BADSL'){document.getElementById('orders').textContent='Filled '+side+' no stop';return;}
  document.getElementById('orders').textContent=side+' '+v[1]+' '+v[0]+' STOP '+v[2]+' TARGET '+v[3];
}
</script></body></html>"""


def _browser() -> str | None:
    for p in (os.getenv("BROWSER_EXECUTABLE"), shutil.which("google-chrome"), shutil.which("chromium")):
        if p and os.path.exists(p):
            return p
    return None


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    d = tmp_path_factory.mktemp("site")
    (d / "index.html").write_text(MOCK)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def ui(calibrated=True):
    import json
    from app.tradovate import UI_FILE

    u = json.loads(UI_FILE.read_text())
    u["calibrated"] = calibrated
    u["price"] = ["#last-price"]
    u["verify_steps"] = [{"do": "wait", "what": "SL", "sel": ["#orders:has-text('STOP {sl}')"], "timeout_ms": 3000}]
    return u


def req(**kw):
    base = dict(signal_id="t", side="BUY", contracts=2, entry=3561.0, sl=3536.2, tp=3597.9, symbol="MGCG7", max_drift=7.0)
    base.update(kw)
    return OrderRequest(**base)


@pytest.mark.skipif(_browser() is None, reason="Chromium/Chrome topilmadi")
def test_full_browser_flow(server, tmp_path, monkeypatch):
    from app.tradovate import TradovateBrowser

    monkeypatch.setenv("BROWSER_EXECUTABLE", _browser())
    s = Settings(bot_token="x", chat_id="1", webhook_secret="s", public_url=None, execution_mode="live",
                 tradovate_url=server, tradovate_user="u", tradovate_pass="p", tradovate_account="TDFY-DEMO-1",
                 session_dir=str(tmp_path))
    asked = []

    async def ask_code(prompt):
        asked.append(prompt)
        return "123456"

    async def run():
        b = TradovateBrowser(s, ask_code, ui())
        try:
            r = await b.execute(req())
            assert r.ok and r.executed, r.text
            assert asked, "kod so'ralishi kerak edi"
            page = await b._get_page()
            assert await page.inner_text("#orders") == "Buy 2 MGCG7 STOP 3536.2 TARGET 3597.9"
            assert r.screenshot and r.screenshot[:4] == b"\x89PNG"

            # narx qochib ketgan — buyurtma yuborilmaydi
            r = await b.execute(req(entry=3540.0))
            assert not r.ok and "qochgan" in r.text

            # SL tasdiqlanmadi — bot pozitsiyani avtomatik yopishi kerak
            r = await b.execute(req())
            assert r.ok
            b.ui["order_steps"][2]["value"] = "BADSL"
            r = await b.execute(req())
            assert not r.ok and "yopildi" in r.text
            assert await page.inner_text("#orders") == "FLAT"

            # boshqa hisob ko'rinsa — bitim ochilmaydi
            b.s = Settings(**{**s.__dict__, "tradovate_account": "BOSHQA-HISOB"})
            r = await b.execute(req())
            assert not r.ok and "hisobi ko'rinmayapti" in r.text
        finally:
            await b.close()

        # kalibrlanmagan fayl bilan — umuman ochilmaydi
        b2 = TradovateBrowser(s, ask_code, ui(calibrated=False))
        r = await b2.execute(req())
        assert not r.ok and "sinalmagan" in r.text

    asyncio.run(run())
