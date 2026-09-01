# TradingView 웹훅 자동매매 봇 (OKX)

트레이딩뷰 전략(별도 비공개 Pine Script, 이 저장소에는 포함되지 않음)의 진입/청산 얼러트를
웹훅으로 받아서, OKX 무기한 스왑(USDT)으로 실제 주문을 내고 텔레그램으로 결과를 알려주는
파이썬 서버입니다. `../bitget/`, `../bybit/`, `../binance/`와 동일한 웹훅 계약(comment 태그)을
쓰므로, 같은 트레이딩뷰 얼러트를 이 봇에도 동시에 연결할 수 있습니다.

이 저장소에는 **매매 전략 자체의 로직(진입/청산 조건, 지표, 파라미터)은 포함되어 있지 않습니다.**

## ⚠️ 먼저 읽어주세요

- 이 코드는 OKX V5 공식 API 문서를 기준으로 작성했고, **실제 데모 계좌로 아직 실측 검증하지
  않았습니다.** 반드시 데모(`OKX_ENV=demo`)로 먼저 충분히 검증하세요.
- 투자 조언이 아니며, 수익을 보장하지 않습니다. 레버리지 선물 거래는 원금 전액 손실 위험이
  있습니다.
- **순서: ① DRY_RUN=true로 로그만 확인 → ② 데모 계좌로 실제 주문 흐름 검증 → ③ 소액 실전.**

## ⚠️ OKX만의 특이사항

- **심볼 표기가 다름**: `BTCUSDT`가 아니라 `BTC-USDT-SWAP`(무기한 스왑). `.env`의
  `TRADE_SYMBOL` 기본값이 이미 이 형식입니다.
- **주문 수량 단위가 "코인"이 아니라 "계약(contract)"**: 예를 들어 BTC-USDT-SWAP 1계약이
  0.01 BTC 같은 식으로 상품마다 계약당 코인 수량(`ctVal`)이 다릅니다. `webhook_bot.py`는
  시작 시 이 값을 조회해서 코인 수량 → 계약 개수로 자동 환산하지만, **이 환산 로직 자체가
  아직 실측 검증되지 않았으니 데모 계좌에서 실제 체결 수량을 반드시 눈으로 확인하세요.**
  환산이 틀리면 의도한 것보다 훨씬 크거나 작은 주문이 나갈 수 있습니다.
- **데모 계좌 키가 실전 키와 별도**: OKX 앱/웹의 "Demo trading" 메뉴에서 발급받은 전용 키가
  필요합니다(Binance 테스트넷과 비슷한 제약, Bitget/Bybit처럼 실전 키 재사용 불가).
- Bitget처럼 `OKX_API_PASSPHRASE`가 필요합니다.

## Bitget/Bybit/Binance 봇과의 차이점 (헤지모드 청산)

Bitget은 청산 주문의 `side`가 포지션과 같은 방향이어야 했지만, OKX는 Bybit/Binance와 마찬가지로
**청산 주문의 `side`가 포지션과 반대 방향**입니다. 롱/숏 "장부" 구분은 `posSide`(`long`/`short`)로
별도 지정합니다 — Bybit의 `positionIdx`, Binance의 `positionSide`와 같은 역할입니다.
`webhook_bot.py`의 주석에 자세히 적혀 있습니다.

## 설치 및 사용

```bash
pip install -r requirements.txt
cp .env.example .env   # OKX_API_KEY/SECRET/PASSPHRASE(데모 전용 키), WEBHOOK_SECRET, TELEGRAM_* 채우기
python webhook_bot.py  # 기본 포트 8003
```

로컬 웹훅 테스트:

```bash
curl -X POST http://localhost:8003/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET과 동일하게>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

트레이딩뷰 얼러트 메시지 JSON, 실전 전환 절차는 `../bitget/README.md`의 3~4단계와 동일한
형식이니 그쪽을 참고하세요 (Webhook URL의 포트만 `8003`으로 바꾸면 됨).

## API 키 발급 시 주의사항

- OKX에서 API 키 생성 시 **"거래" 권한만 활성화**하고 **출금 권한은 절대 켜지 마세요.**
- 가능하면 IP 화이트리스트를 설정하세요.
- `.env` 파일은 git 저장소에 커밋하지 마세요 (`.gitignore`에 이미 포함됨).

## 참고 문서

- [OKX V5 API 인증](https://www.okx.com/docs-v5/en/#overview-rest-authentication-signature)
- [주문 생성](https://www.okx.com/docs-v5/en/#order-book-trading-trade-post-place-order)
- [포지션 모드 설정](https://www.okx.com/docs-v5/en/#trading-account-rest-api-set-position-mode)
- [트레이딩뷰 웹훅 얼러트 문서](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
