# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Binance USDⓈ-M futures trading bot driven by TradingView webhook alerts, not by an in-process
strategy loop. Signal generation lives entirely in a private TradingView Pine Script strategy that
is **not part of this repo**. This project's only job is: receive that strategy's order-fill alerts
over HTTP, translate them into real Binance orders sized against the real account balance, and
report the result to Telegram. Reuses the exact same webhook comment contract as `../bitget/` and
`../bybit/`, so the same TradingView alert JSON can be pointed at all three bots simultaneously.

**Status: written against Binance's official USDⓈ-M Futures API docs, not yet live-exercised
against a real testnet account.** Treat every exchange-specific field name and behavior here as
needing confirmation against a real account before trusting it with money — see "Known gaps" below.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in BINANCE_API_KEY/SECRET (testnet-only keys — see README),
                             # WEBHOOK_SECRET, TELEGRAM_*

# Run the webhook server (defaults: DRY_RUN=true, BINANCE_ENV=testnet)
python webhook_bot.py

# Simulate a TradingView alert locally
curl -X POST http://localhost:8002/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'

python -m py_compile config.py binance_client.py telegram_notifier.py webhook_bot.py
```

## Architecture

**Data flow:** same shape as `../bitget/`/`../bybit/` — `config.py` is the single source of truth,
`binance_client.py` is the only module that talks to Binance's REST API and stays thin/strategy-
unaware, `webhook_bot.py` wires alert classification to order execution.

**Signing:** `BinanceClient._sign` implements Binance's documented scheme: build the full parameter
set (including `timestamp` and `recvWindow`), URL-encode it into a query string, then
`HMAC-SHA256(secret, queryString)` → hex, appended back onto the params as `signature`. Unlike
Bitget/Bybit/OKX, **the whole request (GET and POST alike) travels as query-string parameters, not
a JSON body** — `_request` sends every call via `requests.request(method, url, params=...)`
regardless of verb. Header: `X-MBX-APIKEY` only (no separate signature header). If you touch
`_sign`, re-verify against Binance's docs sample before trusting it.

**Why order size is recomputed server-side instead of trusted from the alert:** identical rationale
to `../bitget/`/`../bybit/` — Pine's `qty` is simulation-only. `webhook_bot.py` classifies the
alert's `comment` via `_classify_alert()` and independently computes `size = live_account_equity ×
margin_pct × leverage / live_mark_price`, using the same two-tier margin_pct split (base vs.
size-up) as the paired Pine strategy — see `MARGIN_PCT_BASE`/`MARGIN_PCT_CONFLUENCE` in
`webhook_bot.py`. `get_account_equity()` reads `totalMarginBalance` from `/fapi/v2/account`
(wallet balance + unrealized PnL), not `/fapi/v2/balance`'s plain `balance` field — chosen to match
Bitget's `accountEquity` semantics (PnL-inclusive) rather than a PnL-blind wallet-balance number.

**comment → action mapping:** identical to `../bitget/`/`../bybit/`'s `_classify_alert()` — same
comment sets, same open/partial-close/full-close semantics. Intentional: all three bots are meant
to be addressable by the same TradingView alert JSON.

**Hedge-mode order shape:**
- Bitget: close order `side` == same direction as the position (`side` is a position-bucket
  selector; `tradeSide` says open vs. close).
- Bybit: close order `side` == opposite of the position + `reduceOnly=true`; bucket selected by
  `positionIdx` (1=long, 2=short).
- **Binance: close order `side` == opposite of the position (same as Bybit), bucket selected by
  `positionSide` (`LONG`/`SHORT`) — but `reduceOnly` must NOT be sent at all in hedge mode.**
  Binance rejects `reduceOnly` alongside a non-`BOTH` `positionSide`; `positionSide` alone already
  disambiguates which book the order reduces, so no extra flag exists or is needed. Open long:
  `side=BUY, positionSide=LONG`. Close long: `side=SELL, positionSide=LONG`. Don't add `reduceOnly`
  here even though it looks like the "safe" thing to do by analogy with Bybit — it will fail.

**Account-level vs. symbol-level settings:** `set_margin_type` is per-symbol (`/fapi/v1/marginType`,
called once at import time, not per-order); `set_position_mode` (hedge on/off,
`/fapi/v1/positionSide/dual`) is account-wide. Both calls are expected to return an "already set"
error (`-4046`/`-4059`) on every restart after the first — `binance_client.py`'s `_IGNORABLE_CODES`
set treats those as success rather than raising, since retrying a no-op setup call every time the
server restarts is normal, not a bug. If Binance ever adds new error codes for other harmless
already-set cases, extend that set rather than loosening the general error handling.

**Position-mode disambiguation (side_hint):** carried over unchanged from `../bitget/`/`../bybit/` —
`get_current_position(side_hint)` filters to the position matching `side_hint` (derived from the
alert's own `action` field via `_expected_close_side`), so out-of-order webhook delivery can't cause
a close alert to hit the wrong side. See `../bitget/CLAUDE.md`'s "Known gaps" for the production
incident that motivated this; the mechanism itself is exchange-agnostic. On Binance, hedge-mode
`positionRisk` returns one row per `positionSide` (LONG/SHORT) with a signed `positionAmt` (positive
for the LONG row, negative for the SHORT row when open, `0` when flat) — `get_current_position` uses
`abs(positionAmt)` as size and `positionSide` directly as the side label, no sign-based direction
inference needed.

## Known gaps / next steps

- **Not yet live-exercised.** No real signed order has been placed against Binance's testnet API.
  Before trusting this with money: get testnet-specific API keys from
  [testnet.binancefuture.com](https://testnet.binancefuture.com), then run the full open →
  partial-close → full-close cycle for both long and short, and confirm every field name this code
  reads (`totalMarginBalance`, `markPrice`, `positionAmt`, `positionSide`) actually appears in the
  real response.
- **`_IGNORABLE_CODES` handling is untested against real responses.** The assumption that `-4046`/
  `-4059` are the only "already configured" codes worth swallowing hasn't been confirmed against a
  live account — if margin type or position mode genuinely fails to apply for another reason, this
  code currently can't tell the difference from a harmless no-op and would log a warning instead of
  failing loudly. Worth tightening once real error codes are observed.
- No idempotency/dedup on the webhook endpoint (same gap as the other two bots, same reasoning).
- No retry/backoff on transient network errors.
- Single-symbol only (`TRADE_CONFIG.symbol`).
