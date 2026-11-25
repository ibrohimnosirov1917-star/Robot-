"""Signal uchun grafik rasmi: shamlar + kirish, SL va TP zonalari."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from .signals import Signal, _tz, fmt_price, tf_label  # noqa: E402

UP, DOWN = "#26a69a", "#ef5350"
TP_FILL, SL_FILL = "#c8e6c9", "#ffcdd2"


def render_chart(sig: Signal, tz_name: str = "Asia/Tashkent") -> bytes | None:
    if not sig.candles:
        return None
    o, h, l, c = (sig.candles[k] for k in ("o", "h", "l", "c"))
    n = len(c)
    future = max(8, n // 4)

    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=110)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Pozitsiya zonasi (TradingView "Long/Short position" ko'rinishida)
    x0, w = n - 1, future
    ax.add_patch(Rectangle((x0, min(sig.entry, sig.tp)), w, abs(sig.tp - sig.entry), color=TP_FILL, alpha=0.8, zorder=0))
    ax.add_patch(Rectangle((x0, min(sig.entry, sig.sl)), w, abs(sig.sl - sig.entry), color=SL_FILL, alpha=0.8, zorder=0))

    # Shamlar
    for i in range(n):
        col = UP if c[i] >= o[i] else DOWN
        ax.vlines(i, l[i], h[i], color=col, linewidth=1, zorder=2)
        body_lo, body_h = min(o[i], c[i]), max(abs(c[i] - o[i]), 0.05)
        ax.add_patch(Rectangle((i - 0.35, body_lo), 0.7, body_h, color=col, zorder=3))

    # Chiziqlar va yozuvlar
    xr = x0 + w
    for y, label, col in (
        (sig.entry, f"Kirish {fmt_price(sig.entry)}", "#455a64"),
        (sig.tp, f"TP {fmt_price(sig.tp)}", "#2e7d32"),
        (sig.sl, f"SL {fmt_price(sig.sl)}", "#c62828"),
    ):
        ax.hlines(y, x0, xr, color=col, linewidth=1.2, linestyles="--" if label.startswith("Kirish") else "-", zorder=4)
        ax.text(xr + 0.3, y, label, va="center", ha="left", fontsize=9, color="white",
                bbox=dict(boxstyle="round,pad=0.25", fc=col, ec="none"), zorder=5)

    # Signal belgisi
    marker_y = h[-1] if sig.side == "SELL" else l[-1]
    ax.annotate(sig.side, xy=(n - 1, marker_y), xytext=(n - 1, marker_y + (1 if sig.side == "SELL" else -1) * (max(h) - min(l)) * 0.08),
                ha="center", fontsize=9, fontweight="bold", color=DOWN if sig.side == "SELL" else UP,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.9),
                arrowprops=dict(arrowstyle="-|>", color=DOWN if sig.side == "SELL" else UP), zorder=6)

    # O'qlar
    lo_all = min(min(l), sig.sl, sig.tp)
    hi_all = max(max(h), sig.sl, sig.tp)
    pad = (hi_all - lo_all) * 0.08
    ax.set_ylim(lo_all - pad, hi_all + pad)
    ax.set_xlim(-1, xr + 7)
    ax.yaxis.tick_right()
    ax.grid(True, color="#eeeeee", linewidth=0.6)
    for s in ("top", "left"):
        ax.spines[s].set_visible(False)

    if sig.bar_time_ms:
        tz = _tz(tz_name)
        step = max(1, n // 6)
        ticks = list(range(0, n, step))
        last_open = sig.bar_time_ms / 1000
        labels = [datetime.fromtimestamp(last_open - (n - 1 - i) * sig.tf_sec, tz=timezone.utc).astimezone(tz).strftime("%H:%M") for i in ticks]
        ax.set_xticks(ticks, labels, fontsize=8)
    else:
        ax.set_xticks([])

    icon = "BUY" if sig.side == "BUY" else "SELL"
    ax.set_title(f"{sig.symbol} {tf_label(sig.tf_sec)} · {icon} · {sig.rr:.1f}R · risk ${sig.risk_usd:.0f}", fontsize=11, loc="left")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
