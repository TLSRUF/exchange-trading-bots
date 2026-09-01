# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An OKX USDT perpetual swap trading bot driven by TradingView webhook alerts, not by an in-process
strategy loop. Signal generation lives entirely in a private TradingView Pine Script strategy that
is **not part of this repo**. This project's only job is: receive that strategy's order-fill alerts
over HTTP, translate them into real OKX orders sized against the real account balance, and report
the result to Telegram. Reuses the exact same webhook comment contract as `../bitget/`, `../bybit/`,
and `../binance/`, so the same TradingView alert JSON can be pointed at all four bots simultaneously.

**Status: public-endpoint parsing, the coin→contract size conversion, and the full webhook request
path have been live-exercised against OKX's real API (no account needed for any of those); everything
that requires account authentication (balance, positions, leverage/hedge-mode setup, actual order
placement) has not been — there is no OKX account available to test against yet.** See "Known gaps"
below for exactly what was and wasn't checked.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in OKX_API_KEY/SECRET/PASSPHRASE (demo-only keys — see README),
                             # WEBHOOK_SECRET, TELEGRAM_*

# Run the webhook server (defaults: DRY_RUN=true, OKX_ENV=demo)
python webhook_bot.py

# Simulate a TradingView alert locally
curl -X POST http://localhost:8003/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'

python -m py_compile config.py okx_client.py telegram_notifier.py webhook_bot.py
```

Note: `webhook_bot.py` makes a real network call to OKX's public instrument-spec endpoint
(`GET /api/v5/public/instruments`) at **import time** (module load, before the FastAPI app starts)
to cache `ctVal`/`lotSz` — this needs network access to `www.okx.com` even to import the module, not
just to run it. `py_compile` above only checks syntax and doesn't trigger this.

## Architecture

**Data flow:** same shape as the other three bots — `config.py` is the single source of truth,
`okx_client.py` is the only module that talks to OKX's REST API and stays thin/strategy-unaware,
`webhook_bot.py` wires alert classification to order execution.

**Signing:** `OkxClient._sign` implements OKX V5's documented scheme: prehash =
`timestamp + METHOD + requestPath(+queryString for GET) + body(JSON string, empty for GET)`,
`HMAC-SHA256(secret, prehash)` → **Base64** (not hex, unlike Bitget/Bybit/Binance). Headers:
`OK-ACCESS-KEY`, `OK-ACCESS-SIGN`, `OK-ACCESS-TIMESTAMP` (ISO 8601 UTC with milliseconds, e.g.
`2020-12-08T09:08:57.715Z` — not a Unix epoch like the other three exchanges), `OK-ACCESS-PASSPHRASE`
(OKX requires a passphrase like Bitget does; Bybit/Binance don't). Demo trading additionally
requires an `x-simulated-trading: 1` header on every request — `_headers()` adds it automatically
when `API_CONFIG.is_demo`. If you touch `_sign`/`_headers`, re-verify against OKX's docs sample
before trusting it.

**Order size is in contracts, not coin — the biggest OKX-specific gotcha:** unlike the other three
bots (which size orders directly in the base coin, e.g. BTC), OKX swap orders take `sz` in **number
of contracts**, where one contract equals a fixed coin amount (`ctVal`) that varies per instrument.
`webhook_bot.py` fetches `ctVal`/`lotSz` once at import time via `get_instrument()` and
`compute_open_size()` converts `coin_qty = notional / price` into `contracts = coin_qty / ctVal`,
then rounds down to a `lotSz` multiple via `okx_client.round_to_lot()`. Get this conversion wrong
and order sizes are off by whatever `ctVal` is for the instrument — verify actual fill sizes on
demo before trusting it. Closes don't need this conversion since `get_current_position()` already
returns position size in contracts (OKX reports it that way), so `close_size = position_size × ratio`
is already in the right unit.

**Why order size is recomputed server-side instead of trusted from the alert:** identical rationale
to the other three bots — Pine's `qty` is simulation-only. `_classify_alert()` and the two-tier
`MARGIN_PCT_BASE`/`MARGIN_PCT_CONFLUENCE` split are unchanged from `../bitget/`.

**comment → action mapping:** identical to the other three bots' `_classify_alert()` — same comment
sets, same open/partial-close/full-close semantics, intentionally shared across all four.

**Hedge-mode order shape:** like Bybit and Binance (not Bitget) — a close order's `side` is the
**actual trade direction, opposite the position**; the position bucket is selected by a separate
field, `posSide` (`long`/`short`), which stays the **same** value for both opening and closing that
bucket (open long: `side=buy, posSide=long`; close long: `side=sell, posSide=long`). No `reduceOnly`
is sent — `posSide` combined with the opposite `side` already disambiguates a reducing trade from a
new position, same reasoning as Binance.

**Account-level vs. symbol-level settings:** `set_position_mode` (hedge on/off,
`/api/v5/account/set-position-mode`) is account-wide, called once at import time. `set_leverage` is
per-instrument *and* per-`posSide` in isolated margin mode — `webhook_bot.py` calls it twice at
startup (once for `long`, once for `short`) rather than once, since OKX allows different leverage
per side in isolated mode and a single call without `posSide` may not cover both. Both calls swallow
`OkxAPIError` with a warning, same pattern as `../bybit/`.

**Position-mode disambiguation (side_hint):** carried over unchanged from the other three bots —
`get_current_position(side_hint)` filters to the position matching `side_hint` (derived from the
alert's own `action` field via `_expected_close_side`), so out-of-order webhook delivery can't cause
a close alert to hit the wrong side. See `../bitget/CLAUDE.md`'s "Known gaps" for the production
incident that motivated this; the mechanism itself is exchange-agnostic.

## Known gaps / next steps

- **Verified without an account (2026-09-01, live against `www.okx.com`, no credentials):**
  `get_mark_price()` and `get_instrument()` parsing against real market/instrument data (`markPx`,
  `ctVal="0.01"`, `lotSz="0.01"` for `BTC-USDT-SWAP` confirmed present and correctly parsed); the
  coin→contract conversion math end-to-end (a hypothetical $4000 notional at the real live mark
  price converted to coin quantity → contracts → lot-rounded, then converted back and checked
  against the original target — matched to within `lotSz` precision); the full webhook request path
  end-to-end via a running server + curl — secret validation (401 on mismatch), `_classify_alert()`
  routing for an unknown comment (200 `ignored`), and clean error propagation for open/close alerts
  (502 with OKX's own `code`/`msg`, not a crash) when the account-authenticated calls fail for lack
  of credentials.
- **Not yet verified: anything requiring real account authentication.** No real signed order has
  been placed, and `totalEq`/`pos`/`posSide` have never been read from a real (non-error) response.
  Before trusting this with money: get demo-only API keys from OKX's "Demo trading" panel, then run
  the full open → partial-close → full-close cycle for both long and short, and confirm those field
  names actually appear as expected in the real response — and specifically confirm the
  contract-size conversion produces the fill size you expect on a real order, not just in the
  standalone calculation checked above.
- **`set_leverage` called twice at startup (once per `posSide`) is unverified** — hasn't been
  confirmed this is actually necessary vs. a single call without `posSide` being sufficient in the
  configured margin mode. Low risk either way (worst case: one of the two calls is a harmless no-op)
  but worth simplifying once confirmed.
- No idempotency/dedup on the webhook endpoint (same gap as the other three bots, same reasoning).
- No retry/backoff on transient network errors.
- Single-symbol only (`TRADE_CONFIG.symbol`).
