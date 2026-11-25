# Salom FVG — Telegram signal bot (Tradeify / Tradovate)

TradingView'dagi **Salom FVG Model v0.8** strategiyasi **MGC1!** grafigida setup topganda
Telegram'ga grafik rasmi, kirish / SL / TP va **MGC kontrakt soni** bilan signal yuboradi:

`🟢 Ruxsat: BUY 1 MGC` · `⏭ O'tkazib yuborish` · `📈 TradingView`

**Ruxsat** bosilsa, bot o'z brauzeri orqali Tradovate'ga (Tradeify hisobi) kirib bitimni
**SL va TP bilan** ochadi va natijani skrinshot bilan yuboradi.

```
TradingView alert ──webhook──▶ /tv/<WEBHOOK_SECRET> ──▶ Telegram (rasm + tugmalar)
Telegram "Ruxsat" ─webhook──▶ /telegram ──▶ bot brauzeri ──▶ Tradovate (Tradeify) ──▶ ✅ / ❌ xabar
```

## Rejimlar (`EXECUTION_MODE`)

| Rejim | Nima bo'ladi |
|---|---|
| `dry` (standart) | Bitim **ochilmaydi**. Bot qanday buyurtma yuborishini ko'rsatadi. |
| `live` | Bot Tradovate'ga kirib bitimni o'zi ochadi. |

`live` rejimda ham `app/tradovate_ui.json` ichida `"calibrated": true` bo'lmaguncha bot
haqiqiy bitim ochmaydi. Bu fayl Tradovate'ning **demo** hisobida sinab chiqilgandan keyin yoqiladi.

## Hajm va risk

MGC: 1 kontrakt = 10 oz, narx $1 yursa = $10.
Kontrakt soni = `RISK_USD ÷ (SL punkt × 10)`, pastga yaxlitlanadi.

| SL | Kontrakt | Risk |
|---|---|---|
| 12 punkt | 2 MGC | $240 |
| 23.6 punkt | 1 MGC | $236 |
| 30 punkt | 1 MGC | $300 ⚠️ (signalda ogohlantirish) |

## Bot nimalarni tekshiradi (Ruxsat bosilganda)

- Signal `SIGNAL_TTL_MIN` (15 daq) dan eski bo'lsa — ochmaydi
- Bugun `MAX_TRADES_PER_DAY` (5) ta bitim ochilgan bo'lsa — ochmaydi
- Signal MGC/GC grafigidan bo'lmasa (masalan XAUUSD) — ochmaydi
- Ekranda `TRADOVATE_ACCOUNT` hisobi ko'rinmasa — ochmaydi
- Bozor narxi signaldan SL masofasining 30% idan ko'p qochgan yoki SL/TP oralig'idan chiqqan bo'lsa — ochmaydi
- Buyurtmadan keyin SL va TP ekranda tasdiqlanmasa — **pozitsiyani darhol yopadi** va xabar beradi
- Bitta signalga ikki marta bosilsa — ikkinchisi e'tiborsiz qoladi

## Railway sozlamalari (Variables)

| O'zgaruvchi | Qiymat |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather bergan token |
| `WEBHOOK_SECRET` | uzun tasodifiy satr |
| `TELEGRAM_CHAT_ID` | `/start` yozganda bot beradi |
| `EXECUTION_MODE` | `dry` yoki `live` |
| `TRADOVATE_USERNAME` | Tradeify dashboard'idagi Tradovate login |
| `TRADOVATE_PASSWORD` | Tradeify dashboard'idagi Tradovate parol |
| `TRADOVATE_ACCOUNT` | hisob nomi/raqami (Tradovate'da ko'rinadigan) |

Ixtiyoriy: `RISK_USD` (250), `MAX_CONTRACTS` (5), `MAX_TRADES_PER_DAY` (5), `MAX_DRIFT_FRAC` (0.3),
`SIGNAL_TTL_MIN` (15), `TRADOVATE_SYMBOL` (bo'sh = joriy kontrakt avtomatik, masalan `MGCG7`),
`TRADOVATE_URL` (`https://trader.tradovate.com`), `DISPLAY_TZ` (`Asia/Tashkent`).

**Volume:** Railway'da servisga `/data` papkasiga Volume ulang. Unda Tradovate sessiyasi saqlanadi,
aks holda har deploy'dan keyin bot kodni qayta so'raydi.

## Buyruqlar

- `/start` — chat ID yoki bot holati
- `/test` — namunaviy signal
- `/status` — rejim, kontrakt, bugungi bitimlar
- `/login` — Tradovate'ga ulanish (skrinshot bilan). Kod so'ralsa — kodni chatga yozing
- `/screen` — Tradovate oynasining hozirgi skrinshoti
- `/flat` — barcha pozitsiya va buyurtmalarni yopish (tasdiq bilan). Bitim ochilgan xabardagi **🔒 Bitimni hozir yopish** tugmasi ham shu ishni qiladi
- `/stats [kun]` — jurnal statistikasi; `/jurnal` — CSV fayl
- `/eslatma` — to'lov va muddatlar (`REMINDERS` o'zgaruvchisi: `2026-12-25=Matn; ...`)

## TradingView alert

1. **MGC1!** grafigini oching (5m) va **Salom FVG Model — v0.8 (Telegram)** strategiyasini qo'shing.
2. **Alert** → *Condition*: shu strategiya → **alert() function calls only**.
3. *Notifications* → **Webhook URL**: `https://<domeningiz>/tv/<WEBHOOK_SECRET>`

## Lokal test

```bash
pip install -r requirements.txt pytest
pytest -q
# brauzer testi (soxta Tradovate sahifasida):
BROWSER_EXECUTABLE=/usr/bin/google-chrome pytest -q tests/test_browser.py
```
