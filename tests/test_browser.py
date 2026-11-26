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

MOCK = r"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="login"><input id="name-input" type="text"><input id="password-input" type="password"
  onkeydown="if(event.key==='Enter'){go('env');setTimeout(()=>{document.getElementById('welcome').hidden=false},2500)}"><button class="fat-button">Войти</button>
  <button class="fat-button">Вход с помощью учетной записи Google</button></div>
<div id="welcome" hidden style="position:fixed;inset:0;background:#222"><button class="close-button" onclick="document.getElementById('welcome').hidden=true">Продолжить</button></div>
<div id="env" hidden><button onclick="if(document.getElementById('welcome').hidden)go('trade')">Доступ к симуляции торговли</button></div>
<div id="trade" hidden>
  <div class="popover" style="position:fixed;top:0;left:0;width:400px;height:300px;background:#333;z-index:9">Новое! ATM
    <button class="btn" onclick="this.parentElement.remove()">Закрыть</button></div>
  <div>СЧЕТ TDFY-DEMO-1</div>
  <div data-testid="typeahead-wrapper" class="typeahead"><input data-testid="order-ticket-symbol-search"
    oninput="ta(this)" onkeydown="if(event.key==='Enter'){this.parentElement.classList.remove('open');sym=this.value;setType(otype)}">
    <ul id="ta-list"></ul></div>
  <div data-testid="order-ticket-action-switch"><label onclick="side='Купить'">Купить</label><label onclick="side='Продать'">Продать</label></div>
  <div data-testid="order-ticket-quantity"><input id="qty"></div>
  <div data-testid="order-ticket-price-input"><input id="price"></div>
  <div data-testid="order-ticket-order-type-select"><div onclick="this.nextElementSibling.hidden=false"><span id="type">МАРКЕТ</span></div>
    <ul hidden><li onclick="setType('МАРКЕТ')"><a>МАРКЕТ</a></li><li onclick="setType('ЛИМИТ')"><a>ЛИМИТ</a></li></ul></div>
  <button data-testid="order-ticket-send-button" onclick="send()">Отправить</button>
  <button data-testid="simple-tpsl-order-ticket-enable-tpsl-button" onclick="this.hidden=true;document.getElementById('tpsl').hidden=false">Включить бракет-ордера</button>
  <div id="tpsl" hidden>
    <div data-testid="simple-tpsl-show-in-units-select"><div onclick="this.nextElementSibling.hidden=false">Тики</div>
      <ul hidden><li onclick="this.closest('ul').hidden=true"><a>Тики</a></li><li><a>Цена</a></li></ul></div>
    <label data-testid="simple-tpsl-bracket-0-take-profit-checkbox-label" class="checkbox" onclick="this.classList.toggle('checkbox-active')">TP</label>
    <div data-testid="simple-tpsl-bracket-0-take-profit-input"><input id="tp" value="2"></div>
    <label data-testid="simple-tpsl-bracket-0-stop-loss-checkbox-label" class="checkbox checkbox-active" onclick="this.classList.toggle('checkbox-active')">SL</label>
    <div data-testid="simple-tpsl-bracket-0-stop-loss-input"><input id="sl" value="2"></div>
  </div>
  <div id="placeholder-for-modals"></div>
  <div data-testid="order-history"><div data-testid="trading-ticket-header" id="orders" style="white-space:pre"></div>
    <div data-testid="order-history-content" id="comment"></div></div>
  <button data-testid="account-info-dropdown-toggle" onclick="document.getElementById('acct').hidden=false">TDFY-DEMO-1 ⌄</button>
  <div id="acct" hidden><div class="risk-settings">Лимит Дневных Потерь $0 Позиции:+ <span id="npos">0</span>/- 0
    <button class="btn btn-danger panic-button" onclick="flat()">Закрыть Все Позиции и Отменить</button></div></div>
</div>
<script>
let side='Купить', otype='МАРКЕТ', sym='';
window.LAST=3561.8; window.REJECT=false; window.FAKE_TP_TICKS=null; window.NO_SL=false;
function go(id){for(const d of ['login','env','trade'])document.getElementById(d).hidden=(d!==id);}
function ta(i){const w=i.parentElement;w.classList.add('open');document.getElementById('ta-list').innerHTML='<li><a>'+i.value+'</a></li>';}
function setType(t){otype=t;document.getElementById('type').textContent=t;
  document.querySelector('[data-testid=order-ticket-order-type-select] ul').hidden=true;
  document.getElementById('price').value = (t==='ЛИМИТ' && sym) ? window.LAST.toFixed(1) : '';}
function send(){
  const m=document.getElementById('placeholder-for-modals'); const q=document.getElementById('qty').value;
  if(!q){m.innerHTML='<div class="popover-title">Order Qty should be specified</div>';return;}
  const tpOn=document.querySelector('[data-testid=simple-tpsl-bracket-0-take-profit-checkbox-label]').classList.contains('checkbox-active');
  const tp=(window.FAKE_TP_TICKS||+document.getElementById('tp').value)/10, sl=+document.getElementById('sl').value/10;
  const buy=side==='Купить', opp=buy?'Продать':'Купить';
  m.innerHTML='<div class="popover-content"><div>'+(tpOn?'['+opp+' '+q+' ЛИМИТ в MKT'+(buy?'+':'-')+tp.toFixed(1)+']':'')+'</div><h3>'+side+' '+q+' МКТ?</h3>'+
    '<div>['+opp+' '+q+' СТОП в MKT'+(buy?'-':'+')+sl.toFixed(1)+']</div>'+
    '<div class="btn-group-justified"><div class="btn-group"><div class="btn" onclick="confirmOrder('+q+','+tp+','+sl+')">'+side+'</div></div>'+
    '<div class="btn-group"><div class="btn">Отменить</div></div></div></div>';
}
function confirmOrder(q,tp,sl){
  document.getElementById('placeholder-for-modals').innerHTML='';
  const o=document.getElementById('orders'), opp=side==='Купить'?'Продать':'Купить';
  if(window.REJECT){
    o.textContent='MGCG7\n#1 '+side+' '+q+' '+sym+' МКТ - Отклонен - 0/1';
    document.getElementById('comment').textContent='Отклонен Риском Your maximum order quantity has been met. Limit: 0 Current: 1';
    return;
  }
  const px=window.LAST, d=side==='Купить'?1:-1;
  o.textContent='MGCG7\n#1 '+side+' '+q+' '+sym+' МКТ - Выполнен - '+q+'/'+q+'\nBrackets\n'+
    (window.NO_SL?'':'#2 '+opp+' '+q+' '+sym+' СТОП в '+(px-d*sl).toFixed(1)+' - Рабочий - 0/'+q+'\n')+
    '#3 '+opp+' '+q+' '+sym+' ЛИМИТ в '+(px+d*tp).toFixed(1)+' - Рабочий - 0/'+q;
  document.getElementById('npos').textContent=q;
}
function flat(){document.getElementById('npos').textContent='0';document.getElementById('orders').textContent='FLAT';
  document.getElementById('acct').hidden=true;}
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
            page = await b._get_page()
            orders = lambda: page.inner_text("#orders")  # noqa: E731

            # 1) to'liq oqim: login → xush kelibsiz → simulyatsiya → buyurtma → tasdiq → tekshiruv
            r = await b.execute(req())
            assert r.ok and r.executed, r.text
            assert "Купить 2 MGCG7 МКТ - Выполнен" in await orders() and "СТОП в 3537.0 - Рабочий" in await orders()
            assert await page.input_value("#tp") == "369" and await page.input_value("#sl") == "248"
            assert r.screenshot and r.screenshot[:4] == b"\x89PNG"

            # 2) SELL
            r = await b.execute(req(side="SELL", entry=3561.0, sl=3575.0, tp=3541.4, contracts=1))
            assert r.ok, r.text
            assert "#1 Продать 1 MGCG7 МКТ - Выполнен" in await orders()

            # 3) narx qochib ketgan — buyurtma yuborilmaydi
            await page.evaluate("document.getElementById('orders').textContent=''")
            r = await b.execute(req(entry=3540.0))
            assert not r.ok and "qochgan" in r.text and await orders() == ""

            # 4) Tradeify rad etdi (Limit: 0) — pozitsiya yo'q, yopishga urinmaydi
            await page.evaluate("window.REJECT=true")
            r = await b.execute(req())
            assert not r.ok and "rad etdi" in r.text and "Limit: 0" in r.text
            assert "Выполнен" not in await orders() and await orders() != "FLAT"
            await page.evaluate("window.REJECT=false")

            # 5) tasdiqlash oynasida TP noto'g'ri — tasdiqlanmaydi
            await page.evaluate("window.FAKE_TP_TICKS=10; document.getElementById('orders').textContent=''")
            r = await b.execute(req())
            assert not r.ok and "tasdiqlash oynasi" in r.text and await orders() == ""
            await page.evaluate("window.FAKE_TP_TICKS=null; document.getElementById('placeholder-for-modals').innerHTML=''")

            # 6) SL buyurtmasi ko'rinmadi — bot pozitsiyani avtomatik yopadi
            await page.evaluate("window.NO_SL=true; document.getElementById('orders').textContent=''")
            r = await b.execute(req())
            assert not r.ok and "yopildi" in r.text and await orders() == "FLAT"
            assert await page.inner_text("#npos") == "0"
            await page.evaluate("window.NO_SL=false")

            # 7) boshqa hisob ko'rinsa — bitim ochilmaydi
            b.s = Settings(**{**s.__dict__, "tradovate_account": "BOSHQA-HISOB"})
            r = await b.execute(req())
            assert not r.ok and "hisobi ko'rinmayapti" in r.text
            b.s = s

            # 8) XAUUSD signali: MGC narxini olish va masofa bo'yicha buyurtma
            await page.evaluate("document.getElementById('orders').textContent=''")
            assert await b.quote("MGCG7") == 3561.8
            rel = req(entry=None, sl=0.0, tp=0.0, relative=True, sl_dist=24.8, tp_dist=36.9, max_drift=float("inf"))
            r = await b.execute(rel)
            assert r.ok and r.executed, r.text
            assert await page.input_value("#tp") == "369" and await page.input_value("#sl") == "248"
            assert "СТОП в 3537.0 - Рабочий" in await orders()

            # 9) favqulodda yopish
            r = await b.flatten()
            assert r.ok and await orders() == "FLAT"
        finally:
            await b.close()

        # kalibrlanmagan fayl bilan — umuman ochilmaydi
        b2 = TradovateBrowser(s, ask_code, ui(calibrated=False))
        r = await b2.execute(req())
        assert not r.ok and "sinalmagan" in r.text

    asyncio.run(run())
