"""Ruxsat bosilganda bitimni ochish.

Rejimlar:
  dry  — bitim OCHILMAYDI, bot faqat live rejimda qanday buyurtma yuborishini ko'rsatadi (standart)
  live — bot o'z brauzeri orqali Tradovate'ga (Tradeify hisobi) kirib bitimni ochadi
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Awaitable, Callable

from .signals import fmt_price


@dataclass(frozen=True)
class OrderRequest:
    signal_id: str
    side: str  # BUY / SELL
    contracts: int
    entry: float | None  # MGC'dagi taxminiy kirish narxi (drift tekshiruvi uchun)
    sl: float
    tp: float
    symbol: str  # Tradovate kontrakti, masalan MGCG7
    max_drift: float  # narx kirishdan shuncha punktdan ko'p qochsa — ochilmaydi
    # XAUUSD signali MGC'da: SL/TP masofasi bo'yicha. entry=None bo'lsa kirish narxi ijro paytidagi narx olinadi
    relative: bool = False
    sl_dist: float = 0.0
    tp_dist: float = 0.0

    def anchored(self, price: float) -> "OrderRequest":
        """Nisbiy buyurtmani berilgan narxga bog'laydi (SL/TP masofalari saqlanadi)."""
        d = 1 if self.side == "BUY" else -1
        return replace(self, entry=price, sl=round(price - d * self.sl_dist, 2), tp=round(price + d * self.tp_dist, 2),
                       max_drift=float("inf"))


@dataclass
class ExecutionResult:
    ok: bool
    text: str
    executed: bool  # True bo'lsa bitim haqiqatan ochilgan
    screenshot: bytes | None = None


AskCode = Callable[[str], Awaitable[str | None]]


def order_lines(req: OrderRequest) -> list[str]:
    if req.entry is None or req.entry == 0.0:
        return [
            f"Kontrakt: <b>{req.symbol}</b> · {req.contracts} ta",
            f"Yo'nalish: <b>{req.side}</b> (bozor narxida)",
            f"SL: kirishdan <b>{req.sl_dist:.1f}</b> punkt · TP: <b>{req.tp_dist:.1f}</b> punkt",
        ]
    return [
        f"Kontrakt: <b>{req.symbol}</b> · {req.contracts} ta",
        f"Yo'nalish: <b>{req.side}</b> (bozor narxida)",
        f"SL: <b>{fmt_price(req.sl)}</b> · TP: <b>{fmt_price(req.tp)}</b>",
    ]


class DryRunExecutor:
    name = "dry"
    live = False

    async def quote(self, symbol: str) -> float | None:
        return None

    async def execute(self, req: OrderRequest) -> ExecutionResult:
        if req.entry is None:
            req = req.anchored(0.0)
        text = "\n".join(["🧪 <b>TEST rejimi — bitim ochilmadi</b>", "", "Live rejimda shunday buyurtma yuborilardi:",
                          *order_lines(req)])
        return ExecutionResult(ok=True, executed=False, text=text)

    async def login(self) -> ExecutionResult:
        return ExecutionResult(ok=False, executed=False, text="🧪 TEST rejimi: Tradovate'ga ulanish o'chiq (EXECUTION_MODE=dry).")

    async def screenshot(self) -> bytes | None:
        return None

    async def flatten(self) -> ExecutionResult:
        return ExecutionResult(ok=False, executed=False, text="🧪 TEST rejimi: yopadigan bitim yo'q.")

    async def describe(self) -> str:
        return "🧪 TEST (bitim ochilmaydi)"

    async def close(self) -> None:
        return None


def make_executor(settings, ask_code: AskCode):
    mode = settings.execution_mode
    if mode in ("dry", "manual", "test"):
        return DryRunExecutor()
    if mode == "live":
        from .tradovate import TradovateBrowser  # Playwright faqat live rejimda kerak

        return TradovateBrowser(settings, ask_code)
    raise ValueError(f"EXECUTION_MODE='{mode}' noto'g'ri (dry yoki live)")
