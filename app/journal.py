"""Savdo jurnali: har bir signal, qaror, ijro va natija (TP/SL) diskka yoziladi.

Fayl: <SESSION_DIR>/journal.jsonl — har qatorda bitta hodisa (JSON). Railway Volume'da
saqlangani uchun bot qayta ishga tushsa ham yo'qolmaydi.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

log = logging.getLogger("journal")


@dataclass
class Trade:
    """Bitta signalning to'liq tarixi (jurnal hodisalaridan yig'iladi)."""
    id: str
    side: str
    symbol: str
    entry: float
    sl: float
    tp: float
    contracts: int
    risk_usd: float
    signal_ts: float
    bar_time_ms: int | None = None
    decision: str | None = None  # BUY / SELL / SKIP
    executed: bool = False
    exec_note: str = ""
    result: str | None = None  # TP / SL
    exit_price: float | None = None
    exit_ts: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def direction(self) -> int:
        return 1 if self.side == "BUY" else -1

    @property
    def sl_dist(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def points(self) -> float | None:
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry) * self.direction

    @property
    def r_multiple(self) -> float | None:
        p = self.points
        return None if p is None or self.sl_dist == 0 else p / self.sl_dist

    def usd(self, point_value: float) -> float | None:
        p = self.points
        return None if p is None else p * point_value * max(self.contracts, 1)

    @property
    def taken(self) -> bool:
        return self.decision in ("BUY", "SELL")

    def session(self) -> str:
        t = (self.bar_time_ms / 1000) if self.bar_time_ms else self.signal_ts
        tz = ZoneInfo("America/New_York") if ZoneInfo else timezone.utc
        h = datetime.fromtimestamp(t, tz=tz).hour
        return "Asia" if (h >= 18 or h < 2) else "London" if h < 8 else "NY" if h < 17 else "Yopiq"


class Journal:
    def __init__(self, path: str):
        self.path = path
        self.trades: dict[str, Trade] = {}
        self._load()

    # ───────── yozish ─────────
    def _append(self, rec: dict) -> None:
        rec = {"ts": time.time(), **rec}
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:  # disk bo'lmasa ham bot ishlashda davom etsin
            log.warning("Jurnalga yozib bo'lmadi: %s", e)
        self._apply(rec)

    def record_signal(self, sig, contracts: int, risk_usd: float) -> None:
        self._append({"type": "signal", "id": sig.id, "side": sig.side, "symbol": sig.symbol, "entry": sig.entry,
                      "sl": sig.sl, "tp": sig.tp, "contracts": contracts, "risk_usd": risk_usd,
                      "bar_time_ms": sig.bar_time_ms, "signal_ts": sig.received_at})

    def record_decision(self, sid: str, decision: str) -> None:
        self._append({"type": "decision", "id": sid, "decision": decision})

    def record_exec(self, sid: str, executed: bool, note: str) -> None:
        self._append({"type": "exec", "id": sid, "executed": executed, "note": note[:300]})

    def record_manual_close(self, sid: str) -> None:
        self._append({"type": "manual_close", "id": sid})

    def record_exit(self, sid: str, result: str, exit_price: float) -> None:
        self._append({"type": "exit", "id": sid, "result": result, "exit": exit_price})

    # ───────── o'qish ─────────
    def _apply(self, rec: dict) -> None:
        t, sid = rec.get("type"), rec.get("id")
        if t == "signal":
            self.trades[sid] = Trade(
                id=sid, side=rec["side"], symbol=rec.get("symbol", ""), entry=float(rec["entry"]), sl=float(rec["sl"]),
                tp=float(rec["tp"]), contracts=int(rec.get("contracts") or 0), risk_usd=float(rec.get("risk_usd") or 0),
                signal_ts=float(rec.get("signal_ts") or rec["ts"]), bar_time_ms=rec.get("bar_time_ms"))
            return
        tr = self.trades.get(sid)
        if tr is None:
            return
        if t == "decision":
            tr.decision = rec["decision"]
        elif t == "exec":
            tr.executed = bool(rec.get("executed"))
            tr.exec_note = rec.get("note", "")
        elif t == "manual_close":
            tr.result = "QO'LDA"
        elif t == "exit":
            if tr.result == "QO'LDA":  # qo'lda yopilgan: strategiya natijasi alohida saqlanadi
                tr.extra["strategy_result"] = rec["result"]
                return
            tr.result = rec["result"]
            tr.exit_price = float(rec["exit"])
            tr.exit_ts = float(rec["ts"])

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    self._apply(json.loads(line))
                except (ValueError, KeyError) as e:
                    log.warning("Jurnal qatori o'qilmadi: %s", e)

    def find_open(self, side: str, entry: float, tol: float = 0.06) -> Trade | None:
        """Yopilish xabariga mos (hali natijasi yo'q) eng so'nggi signal."""
        cands = [t for t in self.trades.values()
                 if (t.result is None or (t.result == "QO'LDA" and "strategy_result" not in t.extra))
                 and t.side == side and abs(t.entry - entry) <= tol]
        return max(cands, key=lambda t: t.signal_ts) if cands else None

    # ───────── hisobot ─────────
    def closed(self) -> list[Trade]:
        return sorted((t for t in self.trades.values() if t.result), key=lambda t: t.signal_ts)

    def stats_text(self, point_value: float, days: int | None = None) -> str:
        since = time.time() - days * 86400 if days else 0
        all_t = [t for t in self.trades.values() if t.signal_ts >= since]
        closed = [t for t in all_t if t.result in ("TP", "SL")]
        manual = [t for t in all_t if t.result == "QO'LDA"]
        taken = [t for t in closed if t.taken]
        skipped = [t for t in closed if t.decision == "SKIP"]
        unanswered = [t for t in closed if t.decision is None]

        def line(ts: list[Trade]) -> str:
            if not ts:
                return "—"
            w = sum(1 for t in ts if t.result == "TP")
            r = sum(t.r_multiple or 0 for t in ts)
            usd = sum(t.usd(point_value) or 0 for t in ts)
            return f"{len(ts)} ta · TP {w} / SL {len(ts) - w} · winrate {100 * w / len(ts):.0f}% · {r:+.1f}R · ${usd:+,.0f}"

        period = f"oxirgi {days} kun" if days else "butun davr"
        out = [f"📊 <b>Jurnal</b> ({period})", "",
               f"Signallar: {len(all_t)} · yopilgan: {len(closed) + len(manual)} · ochiq: {len(all_t) - len(closed) - len(manual)}", "",
               f"🟢 Ruxsat berilgan: {line(taken)}",
               f"   ↳ haqiqatan ochilgan: {line([t for t in taken if t.executed])}",
               f"⏭ O'tkazib yuborilgan: {line(skipped)}",
               f"🤷 Javobsiz qolgan: {line(unanswered)}",
               f"🔒 Qo'lda yopilgan: {len(manual)} ta", "",
               "<b>Sessiyalar bo'yicha (barcha signallar):</b>"]
        for sess in ("Asia", "London", "NY"):
            out.append(f"{sess}: {line([t for t in closed if t.session() == sess])}")
        out += ["", "<b>Yo'nalish bo'yicha:</b>",
                f"BUY: {line([t for t in closed if t.side == 'BUY'])}",
                f"SELL: {line([t for t in closed if t.side == 'SELL'])}"]
        return "\n".join(out)

    def to_csv(self, tz_name: str, point_value: float) -> bytes:
        tz = ZoneInfo(tz_name) if ZoneInfo else timezone.utc
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "sana", "sessiya", "yo'nalish", "kontrakt", "kirish", "SL", "TP", "SL punkt", "qaror",
                    "ochildi", "izoh", "natija", "chiqish", "punkt", "R", "$"])
        for t in sorted(self.trades.values(), key=lambda t: t.signal_ts):
            d = datetime.fromtimestamp(t.signal_ts, tz=tz).strftime("%Y-%m-%d %H:%M")
            r, usd = t.r_multiple, t.usd(point_value)
            w.writerow([t.id, d, t.session(), t.side, t.contracts, t.entry, t.sl, t.tp, f"{t.sl_dist:.2f}",
                        t.decision or "", "ha" if t.executed else "yo'q", t.exec_note, t.result or "",
                        t.exit_price if t.exit_price is not None else "",
                        f"{t.points:.2f}" if t.points is not None else "",
                        f"{r:.2f}" if r is not None else "", f"{usd:.0f}" if usd is not None else ""])
        return ("﻿" + buf.getvalue()).encode("utf-8")  # Excel o'zbekcha harflarni to'g'ri ochishi uchun BOM
