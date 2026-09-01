# Exchange Trading Bots

**Language:** [한국어](./README.md) | English (current)

A collection of auto-trading bots that receive TradingView webhook alerts and execute them as real
orders on different exchanges. The trading strategy itself (entry/exit conditions, indicators) is
**not** included here — each bot is only the execution layer between "an alert arrives" and "a real
order gets placed."

## Layout

All four bots share the exact same webhook comment contract (`Long`/`Short`/`Long-Conf`/
`Short-Conf`/`tphalf`/`tpfull`/`ma200dn`/`ma200up`/`StopLoss`), so the same TradingView alert JSON
can be pointed at any of them simultaneously. The exchange APIs themselves differ a lot (signing
scheme, hedge-mode close-order shape, order-size units), so each implementation is independent —
see each folder's README/CLAUDE.md for the details.

| Folder | Exchange | Default port | Live-verification status |
|---|---|---|---|
| [`bitget/`](./bitget) | Bitget USDT-M futures | 8000 | ✅ Verified live, including account-authenticated calls |
| [`bybit/`](./bybit) | Bybit USDT perpetual futures | 8001 | 🟡 Public API + full webhook flow verified live; account-authenticated parts (balance/positions/orders) unverified |
| [`binance/`](./binance) | Binance USDⓈ-M futures | 8002 | 🟡 Same as above |
| [`okx/`](./okx) | OKX USDT perpetual swap | 8003 | 🟡 Same as above |

For the three non-Bitget bots, the account-authenticated APIs (balance, positions, leverage
setup, real order placement) haven't been verified against a real account yet, since none was
available. What *was* actually run and confirmed live: public-endpoint parsing (price, contract
specs), OKX's coin→contract size conversion math, and the full webhook request path — secret
validation, comment routing, error handling — via a running server hit with curl. The remaining
authenticated parts need a demo/testnet account to verify — see each bot's README, "Read this
first" section.

## Shared design principles

- Order size is never trusted from the alert — it's always recomputed from live account balance.
- Webhook shared-secret authentication.
- `DRY_RUN` on by default; going live requires an explicit confirmation value.
- Order results are reported to Telegram.

## Where and how do I run the server?

For TradingView to reach this bot with a webhook, it needs to be **reachable on the internet, 24/7,
at a fixed address**. Your everyday PC/laptop doesn't fit — it gets turned off and its IP changes.
Here's the path:

### 0. Get a feel for it locally first (no VPS needed)

Before renting a VPS, run `python webhook_bot.py` on your own machine and expose it temporarily
with [ngrok](https://ngrok.com) (`ngrok http 8000`) or a Cloudflare Tunnel, then fire a real
TradingView alert at it to verify the whole flow works. It stops the moment your PC does, so it's
test-only — but it lets you confirm "does this actually work" before spending anything on a VPS.

### 1. Get a VPS

- A tiny instance is enough (around 1 vCPU / 1GB RAM — the bot itself is lightweight).
- Oracle Cloud's Always Free tier, AWS Lightsail, Vultr, DigitalOcean, or any other provider all
  work fine — an Ubuntu/Debian image is recommended.
- Make sure you can SSH into it.

### 2. Deploy to the server

```bash
# after SSHing into the VPS
git clone https://github.com/TLSRUF/exchange-trading-bots.git
cd exchange-trading-bots/bitget          # or bybit/binance/okx
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env                                # fill in API keys, WEBHOOK_SECRET, etc.
```

### 3. Keep it running 24/7 (systemd)

Rather than `nohup ... &` (which dies the moment your SSH session ends), register it as a systemd
service that automatically restarts after a reboot. Create
`/etc/systemd/system/tvbot-bitget.service` (swap the name/path/port per exchange to run all four
bots on one server at once — the ports 8000–8003 already don't collide):

```ini
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
sudo systemctl daemon-reload
sudo systemctl enable --now tvbot-bitget
sudo systemctl status tvbot-bitget   # confirm it started cleanly
journalctl -u tvbot-bitget -f        # tail live logs
```

### 4. Open it up so TradingView can reach it

- Open the relevant port (e.g. 8000) in the VPS firewall *and* the cloud provider's security
  group, so TradingView can actually connect.
- Rather than exposing the raw port, putting an **Nginx reverse proxy + HTTPS (Let's Encrypt)** in
  front is recommended (not strictly required, but it keeps the shared secret off plain HTTP):

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location /bitget/  { proxy_pass http://127.0.0.1:8000/; }
    location /bybit/   { proxy_pass http://127.0.0.1:8001/; }
    location /binance/ { proxy_pass http://127.0.0.1:8002/; }
    location /okx/     { proxy_pass http://127.0.0.1:8003/; }
}
```

Get the certificate with `sudo certbot --nginx`. This tidies the TradingView alert's Webhook URL
into something like `https://your-domain.com/bitget/webhook/tradingview`, and you never have to
expose a raw port number.

## ⚠️ Risk disclosure

- This is not investment advice and does not guarantee profit.
- Leveraged futures trading carries risk of total loss of principal.
- Always verify with DRY_RUN → demo account → small real-money size, in that order, before relying
  on this.
- Final responsibility for any trade this executes, and its outcome, rests entirely with you.
