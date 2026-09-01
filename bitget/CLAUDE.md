# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Bitget USDT-M futures trading bot driven by TradingView webhook alerts, not by an in-process
strategy loop. Signal generation (entries/exits, sizing tiers, take-profit ladder, emergency-exit
condition) lives entirely in a private TradingView Pine Script strategy that is **not part of this
repo**. This project's only job is: receive that strategy's order-fill alerts over HTTP, translate
them into real Bitget orders sized against the real account balance, and report the result to
Telegram.

This bot has gone through at least one prior strategy migration (different comment vocabulary, different
partial-close shape). The `_classify_alert()` comment-tag sets in `webhook_bot.py` are the entire
contract with whatever Pine strategy is currently wired up — if the strategy's `comment=` strings
change, these sets must change in lockstep, and old comment sets should not be silently reused for a
new strategy without checking they still mean the same thing.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in BITGET_API_KEY/SECRET/PASSPHRASE, WEBHOOK_SECRET, TELEGRAM_*

# Run the webhook server (defaults: DRY_RUN=true, BITGET_PRODUCT_TYPE=SUSDT-FUTURES demo)
python webhook_bot.py

# Simulate a TradingView alert locally
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'

# Sanity-check modules compile (there is no test suite in this repo)
python -m py_compile config.py bitget_client.py telegram_notifier.py webhook_bot.py
```

There is no linter, formatter, or test framework configured in this repo. If adding one, match the
existing style (dataclasses for config, plain `requests` calls, Korean-language comments/log/user-
facing messages).

## Architecture

**Data flow:** `config.py` (dataclasses `ApiConfig`/`WebhookConfig`/`TelegramConfig`/`TradeConfig`,
loaded from `.env` via `python-dotenv`) is the single source of truth, imported by
`webhook_bot.py` and `telegram_notifier.py`. `bitget_client.py` is the only module that talks to
Bitget's REST API and should stay exchange-API-shaped (thin wrapper), not strategy-aware.

**Signing:** `BitgetClient._sign` implements Bitget's documented scheme:
`HMAC-SHA256(secret, timestamp + METHOD + requestPath + "?" + queryString + body)`, base64-encoded.
If you touch `_sign`/`_headers`, re-verify against Bitget's docs sample before trusting it, since a
subtly wrong signature fails silently as an auth error, not a crash.

**Why order size is recomputed server-side instead of trusted from the alert:** the Pine strategy's
`qty` is computed against its own `initial_capital` (a simulation-only value), which will not match
the user's real Bitget balance. So `webhook_bot.py` treats the alert's `comment` field purely as an
*intent* signal (`_classify_alert()`: open long, open short, partial close, full close) and
independently computes the real order size from live exchange state:
- **Opens**: `size = live_account_equity × margin_pct × TRADE_CONFIG.leverage / live_mark_price`,
  where `margin_pct` depends on which entry comment arrived (the strategy currently distinguishes a
  base tier and a size-up tier — see `MARGIN_PCT_BASE`/`MARGIN_PCT_CONFLUENCE` in `webhook_bot.py`
  for the actual configured values, kept in code rather than documented here since they must track
  the paired Pine strategy's own sizing inputs exactly).
- **Closes**: size is a fraction of whatever `get_positions()` reports as the *actual currently open*
  position, not anything from the alert. The strategy can fire multiple partial-close alerts per
  trade; this bot doesn't track ladder state itself since each partial-close alert independently asks
  for a fixed fraction of whatever remains open right now (see `PARTIAL_CLOSE_RATIO`).

`alert.contracts`/`alert.position_size` are logged for cross-checking but never used to size an
order. If the Pine strategy's sizing or leverage inputs change, the corresponding constants in
`webhook_bot.py`/`config.py` must be updated to match, or the two will silently diverge (Pine's
backtest sizing vs. this bot's real sizing).

**comment → action mapping:** `_classify_alert()` in `webhook_bot.py` classifies the alert's `comment`
field via exact-set matching, which must line up with the `comment=` strings the paired Pine strategy
actually emits — this is the entire contract between the two projects. Current sets (see
`webhook_bot.py` for the authoritative, up-to-date list):
- `OPEN_LONG_COMMENTS` / `OPEN_SHORT_COMMENTS` — `strategy.entry`'s explicit `comment=`. A `-Conf`
  suffix variant marks the size-up tier so this bot can tell which margin tier applied.
- `PARTIAL_CLOSE_COMMENTS` — a partial-close step (always closes a fixed fraction of whatever's
  currently open, so one tag covers every ladder step).
- `FULL_CLOSE_COMMENTS` — includes the ladder's final full-close step, any emergency-exit close, and
  the stop-loss fill. Some entries are synonyms for the same event: Pine's `comment=` fallback
  defaults to the order id when `comment` isn't explicitly set on `strategy.exit`, so both the
  explicit and the id-fallback spelling are kept in the set so this bot works regardless of which
  variant a given deployed copy of the script is actually generating.

**Order execution:** all opens and closes go through `bitget_client.place_order()` with an explicit
`trade_side` (`"open"` or `"close"`) rather than `flash_close_position()`, specifically because
`flash_close_position()` can only close a position in full — it can't express a partial close. Using
`place_order(..., trade_side="close")` uniformly for both partial and full closes keeps the code path
single. `flash_close_position()` exists in `bitget_client.py` but is currently unused by
`webhook_bot.py`.

**Hedge-mode close direction (important, easy to get backwards):** this account's `posMode` is
`hedge_mode`, where a close order's `side` must equal the *same* direction as the position being
closed, not the opposite (`close long → side="buy"`, `close short → side="sell"`, both with
`trade_side="close"`) — see "Known gaps" below for how this was verified and the bug it caused when
implemented backwards. Don't "fix" `_handle_close`'s `close_side` back to the opposite-of-`holdSide`
logic that looks intuitive at a glance; it's wrong for this account's position mode.

**Webhook auth:** `WEBHOOK_CONFIG.shared_secret` must be present in `.env` *and* match the `secret`
field in the incoming JSON, or the request is rejected with 401 and a Telegram alert fires
(`notify_webhook_rejected`) — TradingView webhooks have no built-in auth, so this shared secret is
the only thing stopping anyone who discovers the URL from placing orders. There is deliberately no
"missing secret = allow" fallback (`not WEBHOOK_CONFIG.shared_secret` alone triggers rejection).

**Telegram notifications fire after the exchange call resolves, not on raw webhook receipt** — this
was a deliberate architecture decision (Python does both the exchange call and the notification, in
that order) so that the Telegram message can report the real outcome (success with fill details, or
the actual error) rather than just "a signal arrived." `telegram_notifier.send_message` never raises
on failure (network error, bad token) — it logs and returns `False` — so a broken Telegram config
degrades to silent (but still logged) notifications, never to a blocked trade.

**Demo vs. live productType:** no separate testnet key — same key reused with `productType` switched
to a demo value (`SUSDT-FUTURES`), `ApiConfig.margin_coin`/`ApiConfig.is_demo` derive the right margin
coin and demo-ness from `productType`.

**Demo symbol mapping (found via live testing, now fixed):** demo mode doesn't just swap the margin
coin — Bitget also renames the *symbol* itself (`BTCUSDT` → `SBTCSUSDT`, i.e. `S` + base coin + `S` +
quote coin), confirmed empirically via `get_contracts()`/`get_all_tickers()` against the real demo
API (real `BTCUSDT` + `SUSDT-FUTURES` fails with `40778: ... does not support SUSDT currency as
margin`; `get_contracts("SUSDT-FUTURES")` only lists demo-prefixed symbols).
`config.resolve_trading_symbol(symbol, product_type)` does this conversion; `webhook_bot.py` computes
`SYMBOL = resolve_trading_symbol(TRADE_CONFIG.symbol, API_CONFIG.product_type)` once at import time
and uses `SYMBOL` (not `TRADE_CONFIG.symbol`) for every exchange call. `TRADE_CONFIG.symbol` stays the
plain real-market symbol the user configures in `.env`; only `SYMBOL` is productType-aware. This will
need a similar mapping if Bitget's live/real symbol format ever diverges from `TRADE_SYMBOL`.

**Safety gate:** `check_live_trading_safety()` in `config.py` runs once at `webhook_bot.py` import
time (module-level, before the FastAPI app even starts accepting requests) and raises immediately if
`DRY_RUN=false` **and** `productType` is a real (non-demo) one **and** `LIVE_TRADING_CONFIRM` isn't
exactly `"I_ACCEPT_THE_RISK"`. This is the last line of defense against an accidental real-money
launch; don't loosen it without the user explicitly asking.

## Known gaps / next steps

- **Race condition bug found and fixed in real live trading**: `_handle_close`'s
  `get_current_position()` used to just return "the first position found for this symbol", assuming
  at most one side (long or short) could ever be open at once. That assumption breaks under
  **TradingView webhook delivery reordering** — Pine may fire a close alert before the new-direction
  entry alert in its own execution order, but there's no guarantee the two HTTP webhook deliveries
  arrive at this server in that same order. When the entry alert arrived first, this bot opened the
  new position, and then `get_current_position()` — now seeing *both* the just-opened new position and
  the still-live old opposite-side position (hedge mode allows both simultaneously) — grabbed
  whichever came first in `get_positions()`'s response and closed *that* instead of the intended one.
  Observed in production: a new-direction open, followed by a close alert that closed the brand-new
  position instead of the pre-existing opposite one, leaving the old position open and undetected
  until the user noticed no reduction in the actual Bitget position. **Fix:**
  `get_current_position(side_hint)` now filters to the position whose `holdSide` matches `side_hint`,
  and `_expected_close_side(alert.action)` derives that hint directly from the alert's own `action`
  field (`{{strategy.order.action}}`) — `action=="sell"` means "closing a long" (`side_hint="long"`),
  `action=="buy"` means "closing a short" (`side_hint="short"`). This makes each close webhook
  self-describing about which side it targets, independent of arrival order or what else got opened
  concurrently; if the hinted side isn't found (already closed / genuine anomaly) it safely no-ops
  with a warning log instead of guessing. `_handle_open` has no equivalent issue since opening doesn't
  need to disambiguate an existing position.

- **Fully live-exercised** against the real demo API (`DRY_RUN=false`, `SUSDT-FUTURES`, real signed
  POST orders — not just dry-run logging): open → partial close → full close on the long side, and
  open → full close on the short side, all round-tripped correctly and left the account flat (0 open
  positions) afterward. Confirmed correct: `resolve_trading_symbol`'s demo symbol mapping,
  `get_account_equity()`'s `accountEquity` field, `get_mark_price()`'s `lastPr` field,
  `get_positions()`'s `holdSide`/`total` fields, and `set_margin_mode`/`set_leverage`/`place_order`'s
  signing on real POST requests.
- **Bug found and fixed during that test**: this demo account's `posMode` is `hedge_mode` (dual-side
  position mode), and in hedge mode Bitget's close-order `side` must match the **same** direction as
  the position, not the opposite — `close long → side=buy, tradeSide=close`; `close short → side=sell,
  tradeSide=close` (confirmed against
  [Bitget's Place Order docs](https://www.bitget.com/api-doc/contract/trade/Place-Order); the initial
  implementation had this backwards and failed with `22002: No position to close` on every close).
  `_handle_close` in `webhook_bot.py` now sets `close_side = "buy" if position["side"] == "long" else
  "sell"`. **If the real-money account ever gets switched to one-way position mode** (`posMode` other
  than `hedge_mode`), this logic — and possibly whether `tradeSide` should be sent at all — needs to be
  re-verified; one-way mode's semantics differ (side alone, `tradeSide` is meant to be ignored there).
- No position-state persistence — the bot is stateless between webhook calls; it always re-derives
  "what to close" from `get_positions()` at call time, so there's no in-memory state to lose on
  restart. This is intentional and should stay this way.
- No retry/backoff on transient network errors in `bitget_client.py`'s `_request`.
- No idempotency/dedup on the webhook endpoint — if TradingView retries a delivery (it does, on
  timeout) the same alert could fire twice. `client_oid` is set per-request but isn't checked for
  prior existence before placing a new order, so a duplicate delivery within the same second could
  still double an order. Worth adding if this becomes a problem in practice.
- Single-symbol only (`TRADE_CONFIG.symbol`). Multi-symbol routing is not in scope yet.
