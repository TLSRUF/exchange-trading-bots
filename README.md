# Exchange Trading Bots

**Language:** 한국어 (현재) | [English](./README.en.md)

TradingView 웹훅 얼러트를 받아서 실제 거래소 주문으로 실행하는 자동매매 봇 모음입니다.
매매 전략(진입/청산 조건, 지표)은 여기 포함되어 있지 않습니다 — 각 봇은 "얼러트 → 실제
주문 실행" 구간만 담당하는 실행 계층입니다.

## 구성

같은 트레이딩뷰 웹훅 얼러트(JSON)를 그대로 여러 거래소 봇에 동시에 연결할 수 있도록, 4개
봇 모두 동일한 comment 계약(Long/Short/Long-Conf/Short-Conf/tphalf/tpfull/ma200dn/ma200up/
StopLoss)을 씁니다. 거래소 API 자체가 서로 달라서(서명 방식, 헤지모드 청산 주문 구조, 주문
수량 단위 등) 구현은 각자 독립적입니다 — 자세한 차이는 각 폴더의 README/CLAUDE.md 참고.

| 폴더 | 거래소 | 기본 포트 | 실측 검증 상태 |
|---|---|---|---|
| [`bitget/`](./bitget) | Bitget USDT-M 선물 | 8000 | ✅ 계정 인증 포함 실거래로 검증됨 |
| [`bybit/`](./bybit) | Bybit USDT 무기한 선물 | 8001 | 🟡 공개 API·전체 웹훅 흐름 실측 완료, 계정 인증 필요한 부분(잔고/포지션/주문)은 미검증 |
| [`binance/`](./binance) | Binance USDⓈ-M 선물 | 8002 | 🟡 위와 동일 |
| [`okx/`](./okx) | OKX USDT 무기한 스왑 | 8003 | 🟡 위와 동일 |

`bitget/`을 제외한 세 봇은 계좌가 없어서 인증이 필요한 API(잔고 조회, 포지션 조회, 레버리지
설정, 실제 주문)는 아직 실제 계좌로 검증하지 못했습니다. 대신 계좌 없이도 되는 부분은 실제로
돌려서 확인했습니다: 시세·계약스펙 등 공개 API 파싱, OKX 계약 수량 환산 계산, 웹훅 시크릿
검증·comment 라우팅·에러 처리까지의 전체 요청 흐름(서버를 띄워 curl로 직접 확인). 계정
인증이 필요한 나머지 부분은 데모/테스트넷 계좌를 만들면 그때 검증해야 합니다 — 각 폴더
README의 "먼저 읽어주세요" 참고.

## 공통 설계 원칙

- 주문 수량은 얼러트에 찍힌 값을 신뢰하지 않고, 항상 실시간 계좌 잔고에서 재계산
- 웹훅 공유 시크릿(shared secret) 인증
- 기본값 DRY_RUN(모의 실행), 실전 전환 시 명시적 확인 값 요구
- 주문 결과를 텔레그램으로 통보

## 서버는 어디서, 어떻게 돌리나요?

트레이딩뷰가 웹훅을 쏘려면 이 봇이 **인터넷에서 접속 가능한 주소로 24시간 켜져 있어야** 합니다.
평소 쓰는 PC/노트북은 껐다 켜지고 IP도 바뀌기 때문에 안 맞습니다 — 아래 순서로 하면 됩니다.

### 0. 먼저 로컬에서 감 잡기 (VPS 없이)

VPS부터 구하지 말고, 우선 내 PC에서 `python webhook_bot.py`로 띄운 다음
[ngrok](https://ngrok.com)(`ngrok http 8000`)이나 Cloudflare Tunnel로 임시 외부 주소를
만들어서 실제 트레이딩뷰 얼러트로 전체 흐름을 먼저 검증하세요. PC를 끄면 같이 끊기니 테스트
전용이지만, "이게 진짜로 작동하는지"를 VPS 비용 들이기 전에 확인할 수 있습니다.

### 1. VPS(가상 서버) 준비

- 사양은 아주 작아도 충분합니다 (1 vCPU / 1GB RAM 정도 — 봇 자체가 가벼움).
- 오라클 클라우드 Always Free, AWS Lightsail, Vultr, DigitalOcean, 국내 클라우드(네이버클라우드
  등) 아무 곳이나 무방합니다 — 우분투/데비안 계열 이미지 추천.
- SSH로 접속 가능한 상태로 만들어두세요.

### 2. 서버에 배포

```bash
# VPS에 SSH 접속한 뒤
git clone https://github.com/TLSRUF/exchange-trading-bots.git
cd exchange-trading-bots/bitget          # 쓸 거래소 폴더로 (bybit/binance/okx도 동일)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env                                # API 키, WEBHOOK_SECRET 등 채우기
```

### 3. 24시간 계속 돌리기 (systemd)

터미널 접속을 끊으면 프로세스도 같이 죽는 `nohup ... &`보다는, 서버 재부팅 후에도 자동으로
다시 뜨는 systemd 서비스로 등록하는 걸 권장합니다. `/etc/systemd/system/tvbot-bitget.service`
파일을 만드세요 (거래소별로 이름/경로/포트만 바꿔서 여러 개 등록하면 한 서버에서 4개 봇을
동시에 돌릴 수 있습니다 — 포트는 8000~8003으로 이미 안 겹치게 되어 있음):

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
sudo systemctl status tvbot-bitget   # 정상 기동 확인
journalctl -u tvbot-bitget -f        # 실시간 로그 보기
```

### 4. 외부(트레이딩뷰)에서 접속 가능하게 열기

- VPS 방화벽 + 클라우드 콘솔의 보안그룹에서 해당 포트(예: 8000)를 열어야 트레이딩뷰가
  접속할 수 있습니다.
- 포트를 그대로 노출하기보다는 **Nginx 리버스 프록시 + HTTPS(Let's Encrypt)** 를 앞에 두는
  걸 권장합니다 (필수는 아니지만, 시크릿이 평문 HTTP로 오가는 걸 막아줌):

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

인증서는 `sudo certbot --nginx`로 발급하면 됩니다. 이렇게 하면 트레이딩뷰 얼러트의 Webhook
URL이 `https://your-domain.com/bitget/webhook/tradingview` 식으로 정리되고, 포트 번호를
외부에 노출할 필요도 없어집니다.

## ⚠️ 리스크 고지

- 투자 조언이 아니며 수익을 보장하지 않습니다.
- 레버리지 선물 거래는 원금 전액 손실 위험이 있습니다.
- 반드시 DRY_RUN → 데모 계좌 → 소액 실전 순서로 검증 후 사용하세요.
- 최종 매매 실행과 그 결과에 대한 책임은 전적으로 사용자 본인에게 있습니다.
