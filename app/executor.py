"""BUY/SELL tugmasi bosilganda nima qilinishi.

Hozir faqat "manual" rejim bor: bot Vest'da qo'lda kiritish uchun tayyor
buyurtma ma'lumotini yuboradi. Vest prop hisoblarida API yo'q, shuning uchun
avtomatik ijro (masalan, brauzer avtomatikasi) keyinroq shu yerga qo'shiladi.
"""

from __future__ import annotations

from dataclasses import dataclass

from .signals import Signal, order_ticket


@dataclass
class ExecutionResult:
    ok: bool
    text: str
    executed: bool  # True bo'lsa bitim haqiqatan ochilgan


class ManualExecutor:
    name = "manual"

    def __init__(self, ttl_min: int):
        self.ttl_min = ttl_min

    async def execute(self, sig: Signal, choice: str) -> ExecutionResult:
        return ExecutionResult(ok=True, executed=False, text=order_ticket(sig, choice, sig.age_min(), self.ttl_min))


def make_executor(mode: str, ttl_min: int):
    if mode != "manual":
        raise ValueError(f"EXECUTION_MODE='{mode}' hali qo'llab-quvvatlanmaydi (faqat 'manual')")
    return ManualExecutor(ttl_min)
