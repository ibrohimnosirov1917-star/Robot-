"""TradingView signalini o'qish va Telegram matnlarini tayyorlash."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


class SignalError(ValueError):
    pass


def _num(payload: dict, key: str) -> float:
    try:
        return float(payload[key])
    except (KeyError, TypeError, ValueError):
        raise SignalError(f"'{key}' maydoni yo'q yoki noto'g'ri")


@dataclass
class Signal:
    side: str  # "BUY" yoki "SELL"
    symbol: str
    entry: float
    sl: float
    tp: float
    qty: float
    risk_usd: float
    rr: float
    bar_time_ms: int | None = None
    tf_sec: int = 300
    candles: dict | None = None  # {"o": [...], "h": [...], "l": [...], "c": [...]}
    id: str = field(default_factory=lambda: secrets.token_hex(4))
    received_at: float = field(default_factory=time.time)
    decision: str | None = None  # "BUY" / "SELL" / "SKIP"

    @classmethod
    def from_payload(cls, payload: dict) -> "Signal":
        side = str(payload.get("side", "")).upper()
        if side not in ("BUY", "SELL"):
            raise SignalError("'side' BUY yoki SELL bo'lishi kerak")
        entry, sl, tp = _num(payload, "entry"), _num(payload, "sl"), _num(payload, "tp")
        if side == "BUY" and not (sl < entry < tp):
            raise SignalError("BUY uchun SL < kirish < TP bo'lishi kerak")
        if side == "SELL" and not (tp < entry < sl):
            raise SignalError("SELL uchun TP < kirish < SL bo'lishi kerak")
        candles = None
        if all(k in payload for k in ("o", "h", "l", "c")):
            arrs = {k: [float(x) for x in payload[k]] for k in ("o", "h", "l", "c")}
            if len({len(v) for v in arrs.values()}) == 1 and len(arrs["c"]) >= 5:
                candles = arrs
        return cls(
            side=side,
            symbol=str(payload.get("symbol", "XAUUSD")),
            entry=entry,
            sl=sl,
            tp=tp,
            qty=float(payload.get("qty", 0) or 0),
            risk_usd=float(payload.get("risk_usd", 50) or 50),
            rr=float(payload.get("rr", 0) or 0) or abs(tp - entry) / abs(entry - sl),
            bar_time_ms=int(payload["time"]) if payload.get("time") else None,
            tf_sec=int(payload.get("tf_sec", 300) or 300),
            candles=candles,
        )

    # ── hisoblar ──
    @property
    def sl_dist(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def tp_dist(self) -> float:
        return abs(self.tp - self.entry)

    @property
    def signal_time(self) -> datetime:
        """Signal sham yopilgan payt (UTC)."""
        if self.bar_time_ms:
            return datetime.fromtimestamp(self.bar_time_ms / 1000 + self.tf_sec, tz=timezone.utc)
        return datetime.fromtimestamp(self.received_at, tz=timezone.utc)

    def age_min(self, now: float | None = None) -> float:
        return ((now or time.time()) - self.received_at) / 60


def _tz(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone(timedelta(hours=5))


def fmt_price(x: float) -> str:
    return f"{x:,.2f}"


def tf_label(tf_sec: int) -> str:
    return f"{tf_sec // 60}m" if tf_sec < 3600 else f"{tf_sec // 3600}h"


def signal_caption(sig: Signal, tz_name: str) -> str:
    icon = "🟢" if sig.side == "BUY" else "🔴"
    t = sig.signal_time.astimezone(_tz(tz_name)).strftime("%d.%m %H:%M")
    sl_sign = "−" if sig.side == "BUY" else "+"
    tp_sign = "+" if sig.side == "BUY" else "−"
    lines = [
        f"{icon} <b>{sig.side} signal</b> · {sig.symbol} {tf_label(sig.tf_sec)}",
        f"⏰ {t} (Toshkent)",
        "",
        f"Kirish: <b>{fmt_price(sig.entry)}</b>",
        f"SL: {fmt_price(sig.sl)}  ({sl_sign}{sig.sl_dist:.2f})",
        f"TP: {fmt_price(sig.tp)}  ({tp_sign}{sig.tp_dist:.2f}) · {sig.rr:.1f}R",
        f"Hajm: <b>{sig.qty:.2f} oz</b> · Risk ${sig.risk_usd:.0f}",
        "",
        "Bitim ochish uchun tugmani bosing 👇",
    ]
    return "\n".join(lines)


def decision_line(choice: str, tz_name: str) -> str:
    now = datetime.now(tz=_tz(tz_name)).strftime("%H:%M")
    if choice == "SKIP":
        return f"\n\n⏭ <b>O'tkazib yuborildi</b> ({now})"
    icon = "🟢" if choice == "BUY" else "🔴"
    return f"\n\n{icon} <b>Tanlandi: {choice}</b> ({now})"


def order_ticket(sig: Signal, choice: str, age_min: float, ttl_min: int) -> str:
    """Vest'da qo'lda kiritish uchun tayyor buyurtma ma'lumoti."""
    icon = "🟢" if choice == "BUY" else "🔴"
    sl_side = "pastda" if choice == "BUY" else "yuqorida"
    tp_side = "yuqorida" if choice == "BUY" else "pastda"
    d = 1 if choice == "BUY" else -1
    sl_px = sig.entry - d * sig.sl_dist
    tp_px = sig.entry + d * sig.tp_dist
    lines = [f"{icon} <b>{choice} — Vest GC-PERP'da oching</b>", ""]
    if choice != sig.side:
        lines += [f"⚠️ Signal <b>{sig.side}</b> edi, siz <b>{choice}</b> tanladingiz.", ""]
    if age_min > ttl_min:
        lines += [f"⚠️ Signal {age_min:.0f} daqiqa oldin chiqqan — narx o'zgargan bo'lishi mumkin.", ""]
    lines += [
        f"Hajm: <b>{sig.qty:.2f}</b>",
        f"SL: kirish narxidan <b>{sig.sl_dist:.2f}</b> punkt {sl_side}",
        f"TP: kirish narxidan <b>{sig.tp_dist:.2f}</b> punkt {tp_side} ({sig.rr:.1f}R)",
        f"Risk: ${sig.risk_usd:.0f}",
        "",
        f"<i>{sig.symbol} bo'yicha: kirish {fmt_price(sig.entry)} · SL {fmt_price(sl_px)} · TP {fmt_price(tp_px)}</i>",
        "<i>Vest narxi biroz farq qilishi mumkin — SL/TP ni punkt masofasi bo'yicha qo'ying.</i>",
    ]
    return "\n".join(lines)


def demo_signal() -> Signal:
    """/test buyrug'i uchun namunaviy signal (sintetik shamlar)."""
    import math
    import random

    rnd = random.Random(7)
    price = 3560.0
    o, h, l, c = [], [], [], []
    for i in range(48):
        drift = -0.9 if i > 30 else 0.15 * math.sin(i / 4)
        op = price
        cl = op + drift + rnd.uniform(-2.2, 2.2)
        if i == 46:
            cl = op - 9.5  # katta impuls shami
        hi = max(op, cl) + rnd.uniform(0.2, 1.8)
        lo = min(op, cl) - rnd.uniform(0.2, 1.8)
        o.append(round(op, 2)); h.append(round(hi, 2)); l.append(round(lo, 2)); c.append(round(cl, 2))
        price = cl
    entry = c[-1]
    sl = round(max(h[-12:]) + 0.5, 2)
    risk = sl - entry
    tp = round(entry - 1.4 * risk, 2)
    return Signal(
        side="SELL", symbol="XAUUSD (TEST)", entry=entry, sl=sl, tp=tp,
        qty=round(50 / risk, 2), risk_usd=50, rr=1.4,
        bar_time_ms=int((time.time() // 300) * 300 * 1000) - 300_000, tf_sec=300,
        candles={"o": o, "h": h, "l": l, "c": c},
    )
