"""MGC uchun hajm (kontrakt soni), narxni tick'ga yaxlitlash va joriy kontraktni tanlash."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

# Oltin fyuchersining asosiy (eng faol) oylari: Fev, Apr, Iyun, Avg, Okt, Dek
_ACTIVE = [(2, "G"), (4, "J"), (6, "M"), (8, "Q"), (10, "V"), (12, "Z")]
# Savdo hajmi keyingi kontraktga taxminan yetkazib berish oyidan oldingi oyning shu sanasida o'tadi
ROLL_DAY = 20


def front_month(root: str = "MGC", today: date | None = None) -> str:
    """Masalan 2026-11-26 → 'MGCG7' (2027 fevral)."""
    today = today or date.today()
    for year in (today.year, today.year + 1):
        for month, code in _ACTIVE:
            prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
            if (today.year, today.month, today.day) < (prev_y, prev_m, ROLL_DAY):
                return f"{root}{code}{year % 10}"
    raise AssertionError("unreachable")


def round_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 6)


@dataclass(frozen=True)
class Plan:
    contracts: int
    risk_per_contract: float
    risk_total: float
    over_risk: bool  # 1 kontrakt ham belgilangan riskdan katta


def plan_size(sl_dist: float, risk_usd: float, point_value: float, max_contracts: int) -> Plan:
    per = sl_dist * point_value
    if per <= 0:
        return Plan(0, 0.0, 0.0, True)
    n = min(int(math.floor(risk_usd / per + 1e-9)), max_contracts)
    if n < 1:
        return Plan(1, per, per, True)
    return Plan(n, per, n * per, False)
