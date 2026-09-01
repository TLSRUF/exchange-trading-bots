# TradingView Webhook Trading Bot (OKX)

**Language:** [한국어](./README.md) | English (current)

A Python server that receives entry/exit alerts from a TradingView strategy (a separate, private
Pine Script — not part of this repo) over webhook, places real orders on OKX USDT perpetual swaps,
and reports the result to Telegram. Uses the exact same webhook contract (comment tags) as
`../bitget/`, `../bybit/`, and `../binance/`, so the same TradingView alert can be wired to this bot
at the same time.

**The trading strategy's own logic (entry/exit conditions, indicators, parameters) is not included
in this repo.**

## ⚠️ Read this first

- The parts that can be verified without an account (public API calls like price/instrument-spec
  lookups, **the coin→contract size conversion math**, and the full webhook request path — secret
  validation, comment routing, error handling) have actually been run and confirmed against a live
  server. But the parts that need account authentication (balance, positions, leverage/hedge-mode
  setup, real order placement) **have not been verified** — there's no demo account to test against.
  Be sure to verify thoroughly on demo (`OKX_ENV=demo`) first.
- Not investment advice, no profit guaranteed. Leveraged futures trading risks total loss of
  principal.
- **Order: ① `DRY_RUN=true` to check logs only → ② verify the real order flow on a demo account →
  ③ small real-money size.**

## ⚠️ OKX-specific quirks

- **Symbol format is different**: not `BTCUSDT` but `BTC-USDT-SWAP` (perpetual swap). `.env`'s
  `TRADE_SYMBOL` default is already in this format.
- **Order size unit is "contracts," not "coin"**: for example, one BTC-USDT-SWAP contract might
  equal 0.01 BTC — the coin-per-contract value (`ctVal`) varies per instrument. `webhook_bot.py`
  fetches this at startup and auto-converts coin quantity → contract count, but **this conversion
  logic itself hasn't been live-verified yet, so watch the actual fill size on a demo account with
  your own eyes.** A wrong conversion could place an order far larger or smaller than intended.
- **Demo account keys are separate from live keys**: you need dedicated keys issued from OKX's
  app/web "Demo trading" menu (similar constraint to Binance's testnet; unlike Bitget/Bybit, you
  can't reuse a live key).
- Like Bitget, `OKX_API_PASSPHRASE` is required.

## Difference from the Bitget/Bybit/Binance bots (hedge-mode close)

Bitget requires a close order's `side` to match the same direction as the position, but OKX — like
Bybit/Binance — uses the **opposite** direction for a close order's `side`. The long/short "book" is
selected separately via `posSide` (`long`/`short`), playing the same role as Bybit's `positionIdx`
and Binance's `positionSide`. Documented in more depth in `webhook_bot.py`'s comments.

## Install and run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in OKX_API_KEY/SECRET/PASSPHRASE (demo-only keys), WEBHOOK_SECRET, TELEGRAM_*
python webhook_bot.py  # default port 8003
```

Local webhook test:

```bash
curl -X POST http://localhost:8003/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<same as WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

The TradingView alert message JSON and the go-live steps follow the same shape as steps 3–4 in
`../bitget/README.en.md` — refer there (just change the Webhook URL's port to `8003`).

## Where do I run the server?

This server needs to be reachable on the internet 24/7 for TradingView's webhook to reach it.
Choosing a VPS, registering it with systemd, and setting up an HTTPS reverse proxy are all covered
in the top-level README's
["Where and how do I run the server?"](../README.en.md#where-and-how-do-i-run-the-server). Here's
just this folder's systemd service for a quick look:

```ini
# /etc/systemd/system/tvbot-okx.service
[Unit]
Description=TradingView Webhook Bot (okx)
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/exchange-trading-bots/okx
ExecStart=/root/exchange-trading-bots/okx/venv/bin/python webhook_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now tvbot-okx
```

## API key setup notes

- When creating the OKX API key, **enable only "Trade" permission** and **never enable withdrawal
  permission.**
- Set an IP whitelist if possible.
- Never commit the `.env` file to the git repo (already covered by `.gitignore`).

## References

- [OKX V5 API authentication](https://www.okx.com/docs-v5/en/#overview-rest-authentication-signature)
- [Place order](https://www.okx.com/docs-v5/en/#order-book-trading-trade-post-place-order)
- [Set position mode](https://www.okx.com/docs-v5/en/#trading-account-rest-api-set-position-mode)
- [TradingView webhook alerts docs](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
