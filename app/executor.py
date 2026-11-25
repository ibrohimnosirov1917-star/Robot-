"""Ruxsat bosilganda bitimni ochish.

Rejimlar:
  dry  — bitim OCHILMAYDI, bot faqat live rejimda qanday buyurtma yuborishini ko'rsatadi (standart)
  live — bot o'z brauzeri orqali Tradovate'ga (Tradeify hisobi) kirib bitimni ochadi
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from .signals import fmt_price


@dataclass(frozen=True)
class OrderRequest:
    signal_id: str
    side: str  # BUY / SELL
    contracts: int
    entry: float  # signal narxi (drift tekshiruvi uchun)
    sl: float
    tp: float
    symbol: str  # Tradovate kontrakti, masalan MGCG7
    max_drift: float  # narx kirishdan shuncha punktdan ko'p qochsa — ochilmaydi


@dataclass
class ExecutionResult:
    ok: bool
    text: str
    executed: bool  # True bo'lsa bitim haqiqatan ochilgan
    screenshot: bytes | None = None


AskCode = Callable[[str], Awaitable[str | None]]


def order_lines(req: OrderRequest) -> list[str]:
    return [
        f"Kontrakt: <b>{req.symbol}</b> · {req.contracts} ta",
        f"Yo'nalish: <b>{req.side}</b> (bozor narxida)",
        f"SL: <b>{fmt_price(req.sl)}</b> · TP: <b>{fmt_price(req.tp)}</b>",
    ]


class DryRunExecutor:
    name = "dry"
    live = False

    async def execute(self, req: OrderRequest) -> ExecutionResult:
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
