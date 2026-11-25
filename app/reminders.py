"""Muddati tugaydigan narsalar (TradingView alert, Railway tarifi va h.k.) haqida Telegram eslatmalari."""

from __future__ import annotations

from datetime import date

REMIND_DAYS = (7, 3, 1, 0)


def parse(spec: str) -> list[tuple[date, str]]:
    out = []
    for part in (spec or "").split(";"):
        if "=" not in part:
            continue
        d, text = part.split("=", 1)
        try:
            out.append((date.fromisoformat(d.strip()), text.strip()))
        except ValueError:
            continue
    return out


def due(spec: str, today: date) -> list[str]:
    """Bugun yuborilishi kerak bo'lgan eslatmalar matni."""
    msgs = []
    for when, text in parse(spec):
        left = (when - today).days
        if left in REMIND_DAYS:
            head = "bugun tugaydi" if left == 0 else f"{left} kundan keyin tugaydi ({when:%d.%m.%Y})"
            msgs.append(f"⏰ <b>Eslatma:</b> {text} — {head}.")
        elif left < 0 and left % 2 == 0 and left >= -10:
            msgs.append(f"⚠️ <b>Muddati o'tgan:</b> {text} ({when:%d.%m.%Y}). Tekshiring!")
    return msgs
