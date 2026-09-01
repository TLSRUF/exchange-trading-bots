# TradingView 웹훅 자동매매 봇 (Bybit)

트레이딩뷰 전략(별도 비공개 Pine Script, 이 저장소에는 포함되지 않음)의 진입/청산 얼러트를
웹훅으로 받아서, Bybit USDT 무기한 선물로 실제 주문을 내고 텔레그램으로 결과를 알려주는
파이썬 서버입니다. `../bitget/`와 동일한 웹훅 계약(comment 태그)을 쓰므로, 같은 트레이딩뷰
얼러트를 이 봇에도 동시에 연결할 수 있습니다.

이 저장소에는 **매매 전략 자체의 로직(진입/청산 조건, 지표, 파라미터)은 포함되어 있지 않습니다.**

## ⚠️ 먼저 읽어주세요

- 이 코드는 Bybit V5 공식 API 문서를 기준으로 작성했고, **실제 데모/테스트넷 계좌로 아직
  실측 검증하지 않았습니다.** `../bitget/` 봇은 실거래로 검증된 반면, 이 봇은 코드 리뷰
  수준입니다 — 반드시 데모(`BYBIT_ENV=demo`)로 먼저 충분히 검증하세요.
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
