# TradingView Webhook Trading Bot (Binance)

**Language:** [한국어](./README.md) | English (current)

A Python server that receives entry/exit alerts from a TradingView strategy (a separate, private
Pine Script — not part of this repo) over webhook, places real orders on Binance USDⓈ-M futures, and
reports the result to Telegram. Uses the exact same webhook contract (comment tags) as `../bitget/`
and `../bybit/`, so the same TradingView alert can be wired to this bot at the same time.

**The trading strategy's own logic (entry/exit conditions, indicators, parameters) is not included
in this repo.**

## ⚠️ Read this first

- The parts that can be verified without an account (public API calls like price lookups, and the
  full webhook request path — secret validation, comment routing, error handling) have actually
  been run and confirmed against a live server. But the parts that need account authentication
  (balance, positions, leverage/margin-type/hedge-mode setup, real order placement) **have not been
  verified** — there's no testnet account to test against. Be sure to verify thoroughly on testnet
  (`BINANCE_ENV=testnet`) first.
- Not investment advice, no profit guaranteed. Leveraged futures trading risks total loss of
  principal.
- **Order: ① `DRY_RUN=true` to check logs only → ② verify the real order flow on testnet →
  ③ small real-money size.**

## ⚠️ Testnet keys are completely separate from live keys

Bitget/Bybit let you reuse your live API key as-is and just switch the base URL (or `productType`)
to reach a demo account, but **Binance's testnet is a fully separate account system**. Sign up
separately at [testnet.binancefuture.com](https://testnet.binancefuture.com) with a GitHub account,
and put the testnet-only API key/secret it issues into `.env`. Putting a live-account key into the
testnet URL will only get you auth errors.

## Differences from the Bitget/Bybit bots (important)

| | Bitget | Bybit | Binance |
|---|---|---|---|
| `side` on a hedge-mode close order | **Same** direction as the position | **Opposite** direction + `reduceOnly` | **Opposite** direction, `reduceOnly` **forbidden** (not allowed) |
| Long/short "book" selector | `side` itself doubles as this | `positionIdx` (1/2) | `positionSide` (`LONG`/`SHORT`) |
| How demo/testnet is reached | Live key as-is, only `productType` changes | Live key as-is, only base URL changes | **A fully separate testnet account/keys** |
| Margin-type/hedge-mode setting scope | Per symbol | Account-wide | Per symbol (margin type) / account-wide (hedge mode) |

The same details are documented in more depth in `webhook_bot.py`'s comments.

## Install and run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in BINANCE_API_KEY/SECRET (testnet-only keys), WEBHOOK_SECRET, TELEGRAM_*
python webhook_bot.py  # default port 8002
```

Local webhook test:

```bash
curl -X POST http://localhost:8002/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<same as WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

The TradingView alert message JSON and the go-live steps follow the same shape as steps 3–4 in
`../bitget/README.en.md` — refer there (just change the Webhook URL's port to `8002`).

## Where do I run the server?

This server needs to be reachable on the internet 24/7 for TradingView's webhook to reach it.
Choosing a VPS, registering it with systemd, and setting up an HTTPS reverse proxy are all covered
in the top-level README's
["Where and how do I run the server?"](../README.en.md#where-and-how-do-i-run-the-server). Here's
just this folder's systemd service for a quick look:

```ini
# /etc/systemd/system/tvbot-binance.service
[Unit]
Description=TradingView Webhook Bot (binance)
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/exchange-trading-bots/binance
ExecStart=/root/exchange-trading-bots/binance/venv/bin/python webhook_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now tvbot-binance
```

## API key setup notes

- When creating the Binance API key, **enable only "Enable Futures" permission** and **never enable
  withdrawal permission.**
- Set an IP whitelist if possible.
- Never commit the `.env` file to the git repo (already covered by `.gitignore`).

## References

- [Binance Futures API overview](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- [New order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)
- [Change position mode](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode)
- [TradingView webhook alerts docs](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
