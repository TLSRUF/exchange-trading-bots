# TradingView 웹훅 자동매매 봇 (Bybit)

**Language:** 한국어 (현재) | [English](./README.en.md)

트레이딩뷰 전략(별도 비공개 Pine Script, 이 저장소에는 포함되지 않음)의 진입/청산 얼러트를
웹훅으로 받아서, Bybit USDT 무기한 선물로 실제 주문을 내고 텔레그램으로 결과를 알려주는
파이썬 서버입니다. `../bitget/`와 동일한 웹훅 계약(comment 태그)을 쓰므로, 같은 트레이딩뷰
얼러트를 이 봇에도 동시에 연결할 수 있습니다.

이 저장소에는 **매매 전략 자체의 로직(진입/청산 조건, 지표, 파라미터)은 포함되어 있지 않습니다.**

## ⚠️ 먼저 읽어주세요

- 계정 없이 검증 가능한 부분(시세·계약 조회 등 공개 API, 웹훅 시크릿 검증/comment 라우팅/
  에러 처리까지의 전체 요청 흐름)은 실제로 서버를 띄워서 확인했습니다. 하지만 **계정 인증이
  필요한 부분(잔고 조회, 포지션 조회, 레버리지/마진모드 설정, 실제 주문 체결)은 아직 검증
  못 했습니다** — Bybit 계정 자체가 없어서 확인 불가능했습니다. `../bitget/` 봇은 이 부분까지
  실거래로 검증된 반면, 이 봇은 그 마지막 단계가 비어있는 상태입니다 — 반드시 데모
  (`BYBIT_ENV=demo`)로 먼저 충분히 검증하세요.
- 투자 조언이 아니며, 수익을 보장하지 않습니다. 레버리지 선물 거래는 원금 전액 손실 위험이
  있습니다.
- **순서: ① DRY_RUN=true로 로그만 확인 → ② 데모(BYBIT_ENV=demo)로 실제 주문 흐름 검증 →
  ③ 소액 실전.**

## Bitget 봇과의 차이점 (중요)

| | Bitget | Bybit |
|---|---|---|
| 헤지모드 청산 주문의 `side` | 포지션과 **같은** 방향 (`side`가 포지션 셀렉터 역할, `tradeSide`로 open/close 구분) | 포지션과 **반대** 방향 + `reduceOnly=true` (`side`가 실제 체결 방향 그대로) |
| 롱/숏 "장부" 구분 | `side` 자체가 겸함 | `positionIdx` (1=롱, 2=숏)로 별도 지정 |
| 데모 계좌 | productType을 `SUSDT-FUTURES`로 바꾸면 됨, **심볼도 `SBTCSUSDT`처럼 바뀜** | `BYBIT_ENV=demo`로 base URL만 바뀜, 심볼(`BTCUSDT`)은 실전과 동일 |
| 마진 모드 설정 단위 | 심볼별 | **계좌 전체**(통합계좌 단위) |

`webhook_bot.py`의 주석에도 같은 내용이 자세히 적혀 있습니다.

## 설치 및 사용

```bash
pip install -r requirements.txt
cp .env.example .env   # BYBIT_API_KEY/SECRET, WEBHOOK_SECRET, TELEGRAM_* 채우기
python webhook_bot.py  # 기본 포트 8001 (Bitget 봇의 8000과 겹치지 않도록)
```

`.env`의 `BYBIT_ENV` 기본값은 `demo`라서, Bybit "데모 트레이딩"(가상자금) 계좌로 붙습니다 —
실전 API 키를 그대로 써도 되고, 데모 계좌는 Bybit 앱/웹의 "Demo Trading" 메뉴에서 활성화해야
합니다.

로컬 웹훅 테스트:

```bash
curl -X POST http://localhost:8001/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET과 동일하게>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

트레이딩뷰 얼러트 메시지 JSON, 실전 전환 절차는 `../bitget/README.md`의 3~4단계와 동일한
형식이니 그쪽을 참고하세요 (Webhook URL의 포트만 `8001`로 바꾸면 됨).

## 서버는 어디서 돌리나요?

이 서버가 24시간 인터넷에서 접속 가능해야 트레이딩뷰 웹훅을 받을 수 있습니다. VPS 고르는
법부터 systemd 등록, HTTPS 리버스 프록시까지는
[최상위 README의 "서버는 어디서, 어떻게 돌리나요?"](../README.md#서버는-어디서-어떻게-돌리나요)에
정리해뒀습니다. 이 폴더용 systemd 서비스만 빠르게 보면:

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

## API 키 발급 시 주의사항

- Bybit에서 API 키 생성 시 **"Contract - Orders & Positions" 권한만 활성화**하고 **출금 권한은
  절대 켜지 마세요.**
- 가능하면 IP 화이트리스트를 설정하세요.
- `.env` 파일은 git 저장소에 커밋하지 마세요 (`.gitignore`에 이미 포함됨).

## 참고 문서

- [Bybit V5 API 개요/인증](https://bybit-exchange.github.io/docs/v5/guide)
- [주문 생성](https://bybit-exchange.github.io/docs/v5/order/create-order)
- [포지션 모드 전환](https://bybit-exchange.github.io/docs/v5/position/position-mode)
- [트레이딩뷰 웹훅 얼러트 문서](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
