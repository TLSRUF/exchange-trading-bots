# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Bybit USDT perpetual futures trading bot driven by TradingView webhook alerts, not by an
in-process strategy loop. Signal generation lives entirely in a private TradingView Pine Script
strategy that is **not part of this repo**. This project's only job is: receive that strategy's
order-fill alerts over HTTP, translate them into real Bybit orders sized against the real account
balance, and report the result to Telegram. Reuses the exact same webhook comment contract as
`../bitget/`, so the same TradingView alert JSON can be pointed at both bots simultaneously.

**Status: written against Bybit's official V5 API docs, not yet live-exercised against a real
demo/testnet account.** Unlike `../bitget/` (which has a documented live-verified round-trip
history), treat every exchange-specific field name and behavior here as needing confirmation
against a real account before trusting it with money — see "Known gaps" below.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in BYBIT_API_KEY/SECRET, WEBHOOK_SECRET, TELEGRAM_*

# Run the webhook server (defaults: DRY_RUN=true, BYBIT_ENV=demo)
python webhook_bot.py

# Simulate a TradingView alert locally
curl -X POST http://localhost:8001/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'

python -m py_compile config.py bybit_client.py telegram_notifier.py webhook_bot.py
```

## Architecture

**Data flow:** same shape as `../bitget/` — `config.py` is the single source of truth (dataclasses
loaded from `.env`), `bybit_client.py` is the only module that talks to Bybit's REST API and stays
thin/strategy-unaware, `webhook_bot.py` wires alert classification to order execution.

**Signing:** `BybitClient._sign` implements Bybit V5's documented scheme:
`HMAC-SHA256(secret, timestamp + api_key + recv_window + payload)` → lowercase hex, where `payload`
is the URL-encoded query string for GET or the raw JSON body string for POST. Headers:
`X-BAPI-API-KEY`, `X-BAPI-TIMESTAMP`, `X-BAPI-SIGN`, `X-BAPI-RECV-WINDOW`. If you touch `_sign`,
re-verify against Bybit's docs sample before trusting it — a subtly wrong signature fails silently
as an auth error, not a crash.

**Why order size is recomputed server-side instead of trusted from the alert:** identical rationale
to `../bitget/` — Pine's `qty` is simulation-only. `webhook_bot.py` classifies the alert's `comment`
via `_classify_alert()` and independently computes `size = live_account_equity × margin_pct ×
leverage / live_mark_price`, using the same two-tier margin_pct split (base vs. size-up) as the
paired Pine strategy — see `MARGIN_PCT_BASE`/`MARGIN_PCT_CONFLUENCE` in `webhook_bot.py`.

**comment → action mapping:** identical to `../bitget/`'s `_classify_alert()` — same comment sets,
same open/partial-close/full-close semantics. This is intentional: both bots are meant to be
addressable by the same TradingView alert JSON.

**Hedge-mode order shape — the single biggest divergence from Bitget (easy to get backwards if you
port logic from that project without reading this):**
- Bitget: a close order's `side` must equal the **same** direction as the position (`side` acts as a
  position-bucket selector; `tradeSide` says whether you're opening or closing that bucket).
- Bybit: a close order's `side` is the **actual trade direction**, always opposite the position
  (`reduceOnly=true` makes it a close instead of a flip) — close long → `side="Sell"`, close short →
  `side="Buy"`. The position bucket itself (long vs. short) is selected by a *separate* field,
  `positionIdx` (`1`=long book, `2`=short book, `0`=one-way mode). Open long uses `side="Buy",
  positionIdx=1`; close long uses `side="Sell", positionIdx=1, reduceOnly=true`. Don't copy Bitget's
  "side stays the same for open and close" mental model here — it's actively wrong for Bybit.

**Account-level vs. symbol-level settings:** Bybit's Unified Trading Account margin mode
(`set-margin-mode`) is an **account-wide** setting, not per-symbol like Bitget/Binance. `webhook_bot.py`
calls it once at import time (not per-order) and swallows failures with a warning log, since a
retry on an account that already has the mode set (or has open positions, which blocks the change)
is expected and harmless to skip. Leverage (`set-leverage`) *is* per-symbol and is still called on
every open, matching `../bitget/`'s pattern.

**Position-mode disambiguation (side_hint):** carried over unchanged from `../bitget/` —
`get_current_position(side_hint)` filters to the position matching `side_hint` (derived from the
alert's own `action` field via `_expected_close_side`), so out-of-order webhook delivery can't cause
a close alert to hit the wrong side. See `../bitget/CLAUDE.md`'s "Known gaps" for the production
incident that motivated this; the mechanism itself is exchange-agnostic.

## Known gaps / next steps

- **Not yet live-exercised.** No real signed order has been placed against Bybit's demo or testnet
  API. Before trusting this with money: run the full open → partial-close → full-close cycle on
  `BYBIT_ENV=demo` for both long and short, and confirm every field name this code reads
  (`totalEquity`, `markPrice`/`lastPrice`, `size`, `side`) actually appears in the real response —
  exchange API responses sometimes differ from docs in practice (this exact class of surprise is
  what `../bitget/CLAUDE.md` documents happening there).
- **`set-margin-mode` / `switch-mode` failure handling is untested.** The code assumes these calls
  either succeed or fail harmlessly (already-set / position open) and swallows `BybitAPIError` with
  a warning either way — hasn't been confirmed against real error codes, so a real misconfiguration
  (e.g. hedge mode never actually enabled) could currently go unnoticed. Consider tightening this
  once the real error codes are known.
- No idempotency/dedup on the webhook endpoint (same gap as `../bitget/`, same reasoning).
- No retry/backoff on transient network errors.
- Single-symbol only (`TRADE_CONFIG.symbol`).
