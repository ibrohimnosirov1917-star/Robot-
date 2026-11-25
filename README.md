# Salom FVG — Telegram signal bot

TradingView'dagi **Salom FVG Model v0.8** strategiyasi setup topganda Telegram'ga
grafik rasmi, kirish / SL / TP / hajm bilan signal yuboradi. Ostida tugmalar bor:

`🟢 BUY` · `🔴 SELL` · `⏭ O'tkazib yuborish` · `🔗 Vest`

Tugma bosilganda bot Vest GC-PERP'da kiritish uchun tayyor buyurtma ma'lumotini
yuboradi (hajm, SL va TP masofasi). Vest prop hisoblarida API yo'q, shuning uchun
hozircha bitim Vest'da qo'lda ochiladi (**manual** rejim).

```
TradingView alert ──webhook──▶ /tv/<WEBHOOK_SECRET> ──▶ Telegram (rasm + tugmalar)
Telegram tugmasi  ──webhook──▶ /telegram           ──▶ buyurtma ma'lumoti
```

## Railway'ga joylash

1. **Railway** → *New Project* → *Deploy from GitHub repo* → shu repozitoriyni tanlang.
   Railway `Dockerfile` orqali o'zi quradi.
2. **Settings → Networking → Generate Domain** — masalan `robot-production.up.railway.app`.
3. **Variables** bo'limiga qo'shing:

   | O'zgaruvchi | Qiymat |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | @BotFather bergan token |
   | `WEBHOOK_SECRET` | uzun tasodifiy satr (masalan 30+ harf/raqam) |
   | `TELEGRAM_CHAT_ID` | keyingi qadamda olinadi |

4. Deploy tugagach, Telegram'da botingizga `/start` yozing — bot **chat ID**ni yuboradi.
   Uni `TELEGRAM_CHAT_ID` ga kiriting (Railway qayta ishga tushiradi).
5. Botga `/test` yozing — namunaviy signal (grafik + tugmalar) kelishi kerak.

Tekshirish: brauzerda `https://<domeningiz>/` ochilsa `{"ok": true, ...}` chiqadi.

## TradingView alert

1. Grafikka **Salom FVG Model — v0.8 (Telegram)** strategiyasini qo'shing (XAUUSD, 5m).
2. **Alert** → *Condition*: shu strategiya → **alert() function calls only**.
3. *Notifications* → **Webhook URL**:
   `https://<domeningiz>/tv/<WEBHOOK_SECRET>`
4. *Message* maydoniga hech narsa yozish shart emas — xabarni strategiyaning o'zi tayyorlaydi.

## Buyruqlar

- `/start` — chat ID yoki bot holati
- `/test` — namunaviy signal
- `/status` — bot holati

## Sozlamalar (ixtiyoriy)

| O'zgaruvchi | Standart | Izoh |
|---|---|---|
| `VEST_URL` | `https://next.vestmarkets.com/trade/GC-PERP` | 🔗 tugmasi havolasi |
| `SIGNAL_TTL_MIN` | `15` | shundan eski signalga tugma bosilsa ogohlantiradi |
| `DISPLAY_TZ` | `Asia/Tashkent` | xabarlardagi vaqt |
| `PUBLIC_URL` | Railway domeni | boshqa hostingda ishlatilsa |
| `EXECUTION_MODE` | `manual` | hozircha faqat `manual` |

## Muhim

- Signal narxlari **XAUUSD (FOREX.com)** bo'yicha. Vest GC-PERP narxi biroz farq
  qilishi mumkin — SL/TP'ni **punkt masofasi** bo'yicha qo'ying (bot ikkalasini ham yozadi).
- Hajm **oz**da hisoblanadi ($50 risk / SL masofasi). Vest'da 1 kontrakt nechaga
  teng ekanini bir marta tekshirib oling.
- Faqat `TELEGRAM_CHAT_ID` dagi chat tugmalarni bosa oladi; begonalarga bot javob bermaydi.

## Lokal test

```bash
pip install -r requirements.txt pytest
pytest -q
```
