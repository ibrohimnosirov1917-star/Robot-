"""Tradovate web (Tradeify hisobi) — botning o'z brauzeri orqali bitim ochish.

Bot Railway serverida Chromium brauzerini ochadi, Tradovate'ga Tradeify bergan login bilan
kiradi (bir martalik kodni Telegram orqali sizdan so'raydi) va sessiyani diskda saqlaydi.
"Ruxsat" bosilganda tugmalarni xuddi odamdek bosib, bitimni SL va TP bilan ochadi.

Qaysi tugma qayerda turgani `tradovate_ui.json` faylida yozilgan. Sayt ko'rinishi o'zgarsa,
faqat shu fayl yangilanadi. Fayl demo hisobda sinalmaguncha (`"calibrated": false`) bot
haqiqiy bitim OCHMAYDI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

from .executor import AskCode, ExecutionResult, OrderRequest, order_lines
from .signals import fmt_price

log = logging.getLogger("tradovate")

UI_FILE = Path(__file__).with_name("tradovate_ui.json")
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


class ExecError(Exception):
    pass


class Rejected(ExecError):
    """Tradovate/Tradeify buyurtmani rad etdi — pozitsiya ochilmagan."""


def load_ui(path: Path = UI_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_price(text: str) -> float | None:
    m = _NUM.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def check_price(req: OrderRequest, price: float) -> str | None:
    """Bozor narxi bitim uchun yaroqlimi. Muammo bo'lsa — sababini qaytaradi."""
    if req.side == "BUY" and not (req.sl < price < req.tp):
        return f"narx {fmt_price(price)} SL va TP oralig'ida emas"
    if req.side == "SELL" and not (req.tp < price < req.sl):
        return f"narx {fmt_price(price)} SL va TP oralig'ida emas"
    drift = abs(price - req.entry)
    if drift > req.max_drift:
        return f"narx signaldan {drift:.1f} punkt qochgan (ruxsat {req.max_drift:.1f})"
    return None


def distances(req: OrderRequest, tick: float = 0.1) -> dict:
    sl_pts, tp_pts = abs(req.entry - req.sl), abs(req.tp - req.entry)
    return {"sl_ticks": int(round(sl_pts / tick)), "tp_ticks": int(round(tp_pts / tick)),
            "sl_pts": f"{round(sl_pts / tick) * tick:.1f}", "tp_pts": f"{round(tp_pts / tick) * tick:.1f}"}


def fill_template(value: str, req: OrderRequest) -> str:
    return value.format(symbol=req.symbol, qty=req.contracts, sl=f"{req.sl:.1f}", tp=f"{req.tp:.1f}",
                        side=req.side, side_title=req.side.title(), side_lower=req.side.lower(),
                        **distances(req))


class TradovateBrowser:
    name = "live"
    live = True

    def __init__(self, settings, ask_code: AskCode, ui: dict | None = None):
        self.s = settings
        self.ask_code = ask_code
        self.ui = ui or load_ui()
        self.lock = asyncio.Lock()
        self._pw = None
        self._ctx = None
        self._page = None

    # ───────── brauzer ─────────
    async def _get_page(self):
        if self._page is not None and not self._page.is_closed():
            return self._page
        from playwright.async_api import async_playwright

        profile = os.path.join(self.s.session_dir, "tradovate-profile")
        os.makedirs(profile, exist_ok=True)
        if self._pw is None:
            self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            profile, headless=True, viewport={"width": 1600, "height": 1000}, locale="en-US",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            executable_path=os.getenv("BROWSER_EXECUTABLE") or None,
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        self._page.set_default_timeout(15000)
        return self._page

    async def close(self) -> None:
        try:
            if self._ctx is not None:
                await self._ctx.close()
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._ctx = self._pw = self._page = None

    async def screenshot(self) -> bytes | None:
        try:
            page = await self._get_page()
            return await page.screenshot(type="png")
        except Exception as e:  # skrinshot olinmasa ham bot ishlashda davom etsin
            log.warning("Skrinshot olinmadi: %s", e)
            return None

    async def _find(self, selectors: list[str], timeout_ms: int = 3000):
        """Ro'yxatdagi birinchi ko'rinib turgan elementni topadi (yo'q bo'lsa None)."""
        page = await self._get_page()
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while True:
            for sel in selectors:
                loc = page.locator(sel).first
                try:
                    if await loc.is_visible():
                        return loc
                except Exception:
                    continue
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.25)

    async def _must(self, selectors: list[str], what: str, timeout_ms: int = 8000):
        loc = await self._find(selectors, timeout_ms)
        if loc is None:
            raise ExecError(f"Tradovate'da topilmadi: {what}")
        return loc

    # ───────── kirish ─────────
    async def _ensure_ready(self) -> None:
        lg = self.ui["login"]
        page = await self._get_page()
        if not page.url.startswith(self.s.tradovate_url):
            await page.goto(self.s.tradovate_url, wait_until="domcontentloaded")
        if await self._find(lg["ready"], 4000):
            return
        if await self._find(lg.get("captcha", []), 500):
            raise ExecError("Tradovate 'robot emasman' tekshiruvini so'rayapti — bot buni o'tolmaydi")
        user = await self._find(lg["user"], 6000)
        if user is not None:
            if not (self.s.tradovate_user and self.s.tradovate_pass):
                raise ExecError("TRADOVATE_USERNAME va TRADOVATE_PASSWORD sozlanmagan")
            await user.fill(self.s.tradovate_user)
            pw = await self._must(lg["password"], "parol maydoni")
            await pw.fill(self.s.tradovate_pass)
            await pw.press("Enter")  # Google/Apple tugmalarini adashib bosmaslik uchun Enter bilan
            await asyncio.sleep(2)
        if await self._find(lg.get("captcha", []), 1500):
            raise ExecError("Tradovate 'robot emasman' tekshiruvini so'rayapti — bot buni o'tolmaydi")
        code_box = await self._find(lg["code_input"], 4000)
        if code_box is not None:
            code = await self.ask_code("🔐 Tradovate bir martalik kod so'rayapti. Kodni shu chatga yozing (5 daqiqa ichida).")
            if not code:
                raise ExecError("Kod kiritilmadi")
            await code_box.fill(code)
            sub = await self._find(lg["code_submit"], 2000)
            if sub is not None:
                await sub.click()
            else:
                await code_box.press("Enter")
            await asyncio.sleep(2)
        welcome = await self._find(lg.get("welcome_close", []), 2000)
        if welcome is not None:
            await welcome.click()
        env = await self._find(lg["env_select"], 4000)
        if env is not None:
            await env.click()
        if not await self._find(lg["ready"], 25000):
            raise ExecError("Tradovate savdo oynasi ochilmadi")

    async def _check_account(self) -> None:
        acc = self.s.tradovate_account
        if not acc:
            return
        page = await self._get_page()
        if acc not in await page.inner_text("body"):
            raise ExecError(f"Ekranda {acc} hisobi ko'rinmayapti — boshqa hisob tanlangan bo'lishi mumkin")

    async def _read_price(self, req: OrderRequest) -> float:
        sels = [fill_template(s, req) for s in self.ui.get("price", [])]
        loc = await self._find(sels, 5000) if sels else None
        price = None
        if loc is not None:
            tag = await loc.evaluate("e => e.tagName")
            price = parse_price(await loc.input_value() if tag in ("INPUT", "TEXTAREA") else await loc.inner_text())
        if price is None:
            raise ExecError("Joriy narxni o'qib bo'lmadi")
        return price

    async def _run(self, steps: list[dict], req: OrderRequest | None, on_submit=None) -> None:
        for i, step in enumerate(steps, 1):
            if req is not None and "side" in step and step["side"] != req.side:
                continue
            what = step.get("what", f"{i}-qadam")
            sels = [fill_template(s, req) if req else s for s in step.get("sel", [])]
            do = step["do"]
            if do == "sleep":
                await asyncio.sleep(float(step.get("sec", 0.5)))
                continue
            if do == "wait_gone":
                if await self._find(sels, 300):
                    await asyncio.sleep(float(step.get("sec", 3)))
                    if await self._find(sels, 300):
                        raise ExecError(f"Kutilgan narsa yo'qolmadi: {what}")
                continue
            if step.get("any_visibility"):
                # Yopiq menyu ichidagi matnni ham o'qish uchun (ko'rinmasa ham)
                page = await self._get_page()
                loc = page.locator(sels[0]).first
                if await loc.count() == 0:
                    raise ExecError(f"Tradovate'da topilmadi: {what}")
            elif step.get("optional"):
                loc = await self._find(sels, int(step.get("timeout_ms", 1500)))
                if loc is None:
                    continue
            else:
                loc = await self._must(sels, what, int(step.get("timeout_ms", 8000)))
            if do == "wait":
                continue
            if do == "expect_text":
                text = await loc.inner_text()
                for needle in step.get("contains", []):
                    n = fill_template(needle, req) if req else needle
                    if n not in text:
                        raise ExecError(f"{what}: '{n}' topilmadi (ekranda: {text[:120]!r})")
                continue
            if do == "expect_lines":
                # Har bir naqsh (regex) ekrandagi kamida bitta qatorga mos kelishi kerak; vaqt tugaguncha qayta tekshiriladi
                deadline = asyncio.get_running_loop().time() + float(step.get("timeout_ms", 8000)) / 1000
                while True:
                    raw = await (loc.text_content() if step.get("any_visibility") else loc.inner_text())
                    lines = re.split(r"\n|(?=#\d)", raw or "")
                    missing = [p for p in step["patterns"] if not any(re.search(p, ln) for ln in lines)]
                    if not missing:
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        raise ExecError(f"{what}: ekranda topilmadi ({', '.join(missing)})")
                    await asyncio.sleep(0.5)
                continue
            if do == "ensure_class":
                if step["cls"] not in ((await loc.get_attribute("class")) or "").split():
                    await loc.click()
                continue
            if do == "fail_if_text":
                text = await loc.inner_text()
                first = next((ln for ln in text.splitlines() if ln.strip().startswith("#")), text[:200])
                if any(w in first for w in step.get("words", [])):
                    reason = next((ln for ln in text.splitlines() if "Limit" in ln or "rejected" in ln.lower()), first)
                    raise Rejected(f"Tradovate buyurtmani rad etdi: {reason[:200]}")
                continue
            if step.get("submit") and on_submit:
                on_submit()
            if do == "click":
                await loc.click()
            elif do == "fill":
                value = fill_template(step["value"], req) if req else step["value"]
                await loc.fill("")
                await loc.fill(value)
                if step.get("enter"):
                    await loc.press("Enter")
            elif do == "type":
                value = fill_template(step["value"], req) if req else step["value"]
                await loc.click()
                await loc.fill("")
                await loc.press_sequentially(value, delay=60)
            elif do == "press":
                await loc.press(step["key"])
            else:
                raise ExecError(f"Noma'lum qadam turi: {do}")
            await asyncio.sleep(float(step.get("pause", 0.3)))

    # ───────── ommaviy amallar ─────────
    async def describe(self) -> str:
        cal = "✅ sozlangan" if self.ui.get("calibrated") else "⚠️ hali demo'da sinalmagan — bitim ochilmaydi"
        return f"🔴 LIVE · Tradovate ({cal})"

    async def login(self) -> ExecutionResult:
        async with self.lock:
            try:
                await self._ensure_ready()
                await self._check_account()
                return ExecutionResult(ok=True, executed=False, text="✅ Tradovate'ga ulandi.", screenshot=await self.screenshot())
            except Exception as e:
                log.exception("Login xatosi")
                return ExecutionResult(ok=False, executed=False, text=f"❌ Ulanib bo'lmadi: {e}", screenshot=await self.screenshot())

    async def execute(self, req: OrderRequest) -> ExecutionResult:
        if not self.ui.get("calibrated"):
            return ExecutionResult(ok=False, executed=False, text=(
                "⚠️ Tradovate tugmalari hali demo hisobda sinalmagan, shuning uchun bitim ochilmadi.\n"
                "Avval demo'da sinov o'tkazamiz (/login va /screen)."))
        async with self.lock:
            sent = False

            def mark_sent():
                nonlocal sent
                sent = True

            try:
                await self._ensure_ready()
                await self._check_account()
                await self._run(self.ui.get("prepare_steps", []), req)
                price = await self._read_price(req)
                problem = check_price(req, price)
                if problem:
                    return ExecutionResult(ok=False, executed=False, text=f"⛔ Bitim ochilmadi: {problem}.",
                                           screenshot=await self.screenshot())
                await self._run(self.ui["order_steps"], req, on_submit=mark_sent)
                await self._run(self.ui.get("verify_steps", []), req)
                text = "\n".join([f"✅ <b>Bitim ochildi</b> (narx ~{fmt_price(price)})", *order_lines(req)])
                return ExecutionResult(ok=True, executed=True, text=text, screenshot=await self.screenshot())
            except Rejected as e:
                return ExecutionResult(ok=False, executed=False, text=f"⛔ {e}", screenshot=await self.screenshot())
            except Exception as e:
                log.exception("Bitim ochishda xato")
                shot = await self.screenshot()
                if not sent:
                    return ExecutionResult(ok=False, executed=False, text=f"❌ Bitim ochilmadi: {e}", screenshot=shot)
                # Buyurtma yuborilgan, lekin SL/TP tasdiqlanmadi — xavfsizlik uchun hammasini yopamiz
                closed = await self._flatten_unlocked()
                return ExecutionResult(ok=False, executed=False, screenshot=await self.screenshot() or shot, text=(
                    f"🚨 Buyurtma yuborildi, lekin tekshiruvdan o'tmadi: {e}\n"
                    + ("Xavfsizlik uchun pozitsiya yopildi." if closed.ok else
                       "⚠️ Pozitsiyani avtomatik yopib bo'lmadi — Tradovate/TradingView'da DARHOL tekshiring!")))

    async def _flatten_unlocked(self) -> ExecutionResult:
        try:
            await self._ensure_ready()
            await self._run(self.ui["flatten_steps"], None)
            return ExecutionResult(ok=True, executed=True, text="✅ Barcha pozitsiya va buyurtmalar yopildi.",
                                   screenshot=await self.screenshot())
        except Exception as e:
            log.exception("Yopishda xato")
            return ExecutionResult(ok=False, executed=False, text=f"❌ Yopib bo'lmadi: {e}. Qo'lda tekshiring!",
                                   screenshot=await self.screenshot())

    async def flatten(self) -> ExecutionResult:
        async with self.lock:
            return await self._flatten_unlocked()
