# TradingView Webhook Trading Bot (Bitget)

**Language:** [한국어](./README.md) | English (current)

A Python server that receives entry/exit alerts from a TradingView strategy (a separate, private
Pine Script — not part of this repo) over webhook, places real orders on Bitget USDT-M futures, and
reports the result to Telegram.

**The trading strategy's own logic (entry/exit conditions, indicators, parameters) is not included
in this repo.** What's here is only the execution layer that turns an alert into a real, safely
sized exchange order.

## ⚠️ Read this first (risk disclosure)

- This code is not investment advice and does not guarantee profit.
- Leveraged futures trading carries risk of total loss and liquidation. Only trade what you can
  afford to lose.
- **Follow this order: ① `DRY_RUN=true` to check logs only → ② verify the real order flow on a
  demo account → ③ small real-money size.**
- This bot is a reference tool. Final responsibility for any trade it executes rests entirely with
  you.

## Overall flow

```
TradingView (Pine strategy alert)
   │  webhook POST (JSON)
   ▼
webhook_bot.py  (FastAPI, runs continuously on a server/VPS)
   │  1. verify secret
   │  2. decide the action from `comment` (open / partial close / full close)
   │  3. recompute size from live account balance/position instead of trusting the alert's number
   ▼
bitget_client.py → executes the order via Bitget's REST API
   │
   ▼
telegram_notifier.py → reports success/failure to Telegram
```

### Why order size isn't taken directly from the TradingView alert

The Pine strategy's order size is computed against the script's own `initial_capital` (a
simulation-only value). If the real exchange balance differs from that (it usually does), using the
alert's number directly would make the position size completely wrong. So:

- **Opens**: the `comment` only tells the bot *what kind* of entry this is; the bot computes the
  actual size itself from the live account balance.
- **Closes**: the bot decides how much to close (all or part) based on the *actual currently open*
  position size it reads from the exchange.

The `contracts`/`position_size` values TradingView sends are logged for cross-checking only — they
never determine the real order size.

## Folder layout

| File | Role |
|---|---|
| `config.py` | API/webhook/Telegram/trading settings (all read from `.env`) |
| `bitget_client.py` | Bitget API signing/request client |
| `webhook_bot.py` | FastAPI server that receives the TradingView webhook and places Bitget orders (entry point) |
| `telegram_notifier.py` | Sends Telegram notifications (called after an order result is known) |

## Install

```bash
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in:

- `BITGET_API_KEY` / `BITGET_API_SECRET` / `BITGET_API_PASSPHRASE`
- `WEBHOOK_SECRET` — any long random string (must match exactly what's in the TradingView alert JSON)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional; without these, only Telegram notifications
  are disabled, everything else still works
- `TRADE_SYMBOL`, `MARGIN_MODE`, `LEVERAGE`, `DRY_RUN` — adjust as needed

## Step 1 — DRY RUN to check the logic only

```bash
python webhook_bot.py
```

`DRY_RUN` defaults to `true`, so incoming webhooks are logged (and reported to Telegram as
simulated) without placing a real order. You can simulate a webhook directly like this:

```bash
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<same as WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

## Step 2 — Verify the real order flow on a demo account

Bitget has no separate testnet keys. Use your regular API key as-is, with `.env`'s
`BITGET_PRODUCT_TYPE=SUSDT-FUTURES` (the default) to use demo balance.

1. Set `DRY_RUN=false` in `.env` (this turns on without needing `LIVE_TRADING_CONFIRM`, since a
   `productType` starting with `S` is demo — see the safety gate in `config.py`).
2. Run `python webhook_bot.py`, then send the `curl` requests above in the order open → partial
   close → full close, and confirm each is reflected correctly on the real demo account.

> Demo mode doesn't just swap the margin coin — it renames the symbol itself too (`BTCUSDT` →
> `SBTCSUSDT`), which `config.py`'s `resolve_trading_symbol()` handles automatically. Leave `.env`'s
> `TRADE_SYMBOL` as the plain real-market symbol at all times.

## Step 3 — Wire up the TradingView alert

1. Add the strategy to a chart and create an alert from the Strategy tab.
2. **Webhook URL**: `http://<your server address>:8000/webhook/tradingview`
3. Put this JSON in the alert **Message** field as-is (using TradingView's placeholders):

   ```json
   {
     "secret": "<same as WEBHOOK_SECRET in .env>",
     "symbol": "{{ticker}}",
     "action": "{{strategy.order.action}}",
     "contracts": "{{strategy.order.contracts}}",
     "position_size": "{{strategy.position_size}}",
     "price": "{{close}}",
     "comment": "{{strategy.order.comment}}",
     "time": "{{time}}"
   }
   ```

4. Create the alert with the "Order fills only" condition, and the `comment` field will carry
   whatever tag the strategy embedded. `webhook_bot.py` classifies actions purely from this
   `comment` value — if the strategy's comment strings ever change, the classification sets at the
   top of `webhook_bot.py` must change with them.

## Step 4 — Go live

1. Change `.env`'s `BITGET_PRODUCT_TYPE=USDT-FUTURES`, and confirm your real API key.
2. With `DRY_RUN=false` and a real `productType`, the server won't start unless you explicitly set
   `LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK` (a last-line-of-defense safety gate — see `config.py`).
3. The server needs to run 24/7 or you'll miss alerts. For *where and how* to keep this running,
   see the top-level README's
   ["Where and how do I run the server?"](../README.en.md#where-and-how-do-i-run-the-server)
   for VPS selection, systemd setup, and an HTTPS reverse proxy. Here's just this folder's systemd
   unit for a quick look:

   ```ini
   # /etc/systemd/system/tvbot-bitget.service
   [Unit]
   Description=TradingView Webhook Bot (bitget)
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/root/exchange-trading-bots/bitget
   ExecStart=/root/exchange-trading-bots/bitget/venv/bin/python webhook_bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

   ```bash
   sudo systemctl daemon-reload && sudo systemctl enable --now tvbot-bitget
   ```
4. Open `WEBHOOK_PORT` (default 8000) in your firewall (and cloud security group) so TradingView
   can reach it — or, as recommended in the guide above, put an Nginx reverse proxy with HTTPS in
   front instead of exposing the raw port.

## API key setup notes

- When creating the Bitget API key, **enable only "Futures Trading" permission** and **never enable
  withdrawal permission.**
- Set an IP whitelist if possible, so a leaked key can't be used from anywhere else.
- Never commit the `.env` file to the git repo (already covered by `.gitignore`).

## References

- [Bitget Futures API overview](https://www.bitget.com/api-doc/contract/intro)
- [Signing scheme](https://www.bitget.com/api-doc/common/signature)
- [Place Order API](https://www.bitget.com/api-doc/contract/trade/Place-Order)
- [TradingView webhook alerts docs](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
