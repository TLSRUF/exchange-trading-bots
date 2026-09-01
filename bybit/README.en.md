# TradingView Webhook Trading Bot (Bybit)

**Language:** [한국어](./README.md) | English (current)

A Python server that receives entry/exit alerts from a TradingView strategy (a separate, private
Pine Script — not part of this repo) over webhook, places real orders on Bybit USDT perpetual
futures, and reports the result to Telegram. Uses the exact same webhook contract (comment tags) as
`../bitget/`, so the same TradingView alert can be wired to this bot at the same time.

**The trading strategy's own logic (entry/exit conditions, indicators, parameters) is not included
in this repo.**

## ⚠️ Read this first

- The parts that can be verified without an account (public API calls like price/contract lookups,
  and the full webhook request path — secret validation, comment routing, error handling) have
  actually been run and confirmed against a live server. But the parts that need account
  authentication (balance, positions, leverage/margin-mode setup, real order placement) **have not
  been verified** — there's no Bybit account to test against. The `../bitget/` bot has been verified
  live all the way through that last step; this one hasn't yet — be sure to verify thoroughly on
  demo (`BYBIT_ENV=demo`) first.
- Not investment advice, no profit guaranteed. Leveraged futures trading risks total loss of
  principal.
- **Order: ① `DRY_RUN=true` to check logs only → ② verify the real order flow on demo
  (`BYBIT_ENV=demo`) → ③ small real-money size.**

## Differences from the Bitget bot (important)

| | Bitget | Bybit |
|---|---|---|
| `side` on a hedge-mode close order | **Same** direction as the position (`side` acts as the position selector; `tradeSide` marks open vs. close) | **Opposite** direction + `reduceOnly=true` (`side` is the actual trade direction) |
| Long/short "book" selector | `side` itself doubles as this | Separate `positionIdx` (1=long, 2=short) |
| Demo account | Switch `productType` to `SUSDT-FUTURES` — **the symbol changes too**, e.g. `SBTCSUSDT` | `BYBIT_ENV=demo` only changes the base URL; the symbol (`BTCUSDT`) stays the same as live |
| Margin-mode setting scope | Per symbol | **Account-wide** (Unified Trading Account level) |

The same details are documented in more depth in `webhook_bot.py`'s comments.

## Install and run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in BYBIT_API_KEY/SECRET, WEBHOOK_SECRET, TELEGRAM_*
python webhook_bot.py  # default port 8001 (kept distinct from Bitget's 8000)
```

`.env`'s `BYBIT_ENV` defaults to `demo`, which connects to Bybit's "Demo Trading" (virtual funds)
account — you can reuse your live API key as-is, but the demo account itself needs to be activated
from Bybit's app/web "Demo Trading" menu first.

Local webhook test:

```bash
curl -X POST http://localhost:8001/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<same as WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

The TradingView alert message JSON and the go-live steps follow the same shape as steps 3–4 in
`../bitget/README.en.md` — refer there (just change the Webhook URL's port to `8001`).

## Where do I run the server?

This server needs to be reachable on the internet 24/7 for TradingView's webhook to reach it.
Choosing a VPS, registering it with systemd, and setting up an HTTPS reverse proxy are all covered
in the top-level README's
["Where and how do I run the server?"](../README.en.md#where-and-how-do-i-run-the-server). Here's
just this folder's systemd service for a quick look:

```ini
# /etc/systemd/system/tvbot-bybit.service
[Unit]
Description=TradingView Webhook Bot (bybit)
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/exchange-trading-bots/bybit
ExecStart=/root/exchange-trading-bots/bybit/venv/bin/python webhook_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now tvbot-bybit
```

## API key setup notes

- When creating the Bybit API key, **enable only "Contract - Orders & Positions" permission** and
  **never enable withdrawal permission.**
- Set an IP whitelist if possible.
- Never commit the `.env` file to the git repo (already covered by `.gitignore`).

## References

- [Bybit V5 API overview/authentication](https://bybit-exchange.github.io/docs/v5/guide)
- [Create order](https://bybit-exchange.github.io/docs/v5/order/create-order)
- [Switch position mode](https://bybit-exchange.github.io/docs/v5/position/position-mode)
- [TradingView webhook alerts docs](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
