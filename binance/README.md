# TradingView 웹훅 자동매매 봇 (Binance)

트레이딩뷰 전략(별도 비공개 Pine Script, 이 저장소에는 포함되지 않음)의 진입/청산 얼러트를
웹훅으로 받아서, Binance USDⓈ-M 선물로 실제 주문을 내고 텔레그램으로 결과를 알려주는
파이썬 서버입니다. `../bitget/`, `../bybit/`와 동일한 웹훅 계약(comment 태그)을 쓰므로,
같은 트레이딩뷰 얼러트를 이 봇에도 동시에 연결할 수 있습니다.

이 저장소에는 **매매 전략 자체의 로직(진입/청산 조건, 지표, 파라미터)은 포함되어 있지 않습니다.**

## ⚠️ 먼저 읽어주세요

- 계정 없이 검증 가능한 부분(시세 조회 등 공개 API, 웹훅 시크릿 검증/comment 라우팅/에러
  처리까지의 전체 요청 흐름)은 실제로 서버를 띄워서 확인했습니다. 하지만 **계정 인증이
  필요한 부분(잔고 조회, 포지션 조회, 레버리지/마진타입/헤지모드 설정, 실제 주문 체결)은
  아직 검증 못 했습니다** — 테스트넷 계정 자체가 없어서 확인 불가능했습니다. 반드시
  테스트넷(`BINANCE_ENV=testnet`)으로 먼저 충분히 검증하세요.
- 투자 조언이 아니며, 수익을 보장하지 않습니다. 레버리지 선물 거래는 원금 전액 손실 위험이
  있습니다.
- **순서: ① DRY_RUN=true로 로그만 확인 → ② 테스트넷으로 실제 주문 흐름 검증 → ③ 소액 실전.**

## ⚠️ 테스트넷 키는 실전 키와 완전히 다릅니다

Bitget/Bybit은 "실전 API 키 그대로, base URL(또는 productType)만 데모로 바꾸면" 가상자금
계좌로 붙지만, **Binance 테스트넷은 별도의 계정 체계**입니다.
[testnet.binancefuture.com](https://testnet.binancefuture.com)에서 GitHub 계정으로 따로
가입하고, 그 사이트에서 발급한 테스트넷 전용 API 키/시크릿을 `.env`에 넣어야 합니다. 실전
계좌에서 발급한 키를 테스트넷 URL에 넣으면 인증 오류만 납니다.

## Bitget/Bybit 봇과의 차이점 (중요)

| | Bitget | Bybit | Binance |
|---|---|---|---|
| 헤지모드 청산 주문의 `side` | 포지션과 **같은** 방향 | 포지션과 **반대** 방향 + `reduceOnly` | 포지션과 **반대** 방향, `reduceOnly` **금지**(허용 안 됨) |
| 롱/숏 "장부" 구분 | `side` 자체가 겸함 | `positionIdx`(1/2) | `positionSide`(`LONG`/`SHORT`) |
| 데모 계좌 전환 방식 | 실전 키 그대로, productType만 변경 | 실전 키 그대로, base URL만 변경 | **완전히 별도의 테스트넷 계정/키** |
| 마진타입/헤지모드 설정 단위 | 심볼별 | 계좌 전체 | 심볼별(마진타입) / 계좌 전체(헤지모드) |

`webhook_bot.py`의 주석에도 같은 내용이 자세히 적혀 있습니다.

## 설치 및 사용

```bash
pip install -r requirements.txt
cp .env.example .env   # BINANCE_API_KEY/SECRET(테스트넷 전용 키), WEBHOOK_SECRET, TELEGRAM_* 채우기
python webhook_bot.py  # 기본 포트 8002
```

로컬 웹훅 테스트:

```bash
curl -X POST http://localhost:8002/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET과 동일하게>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

트레이딩뷰 얼러트 메시지 JSON, 실전 전환 절차는 `../bitget/README.md`의 3~4단계와 동일한
형식이니 그쪽을 참고하세요 (Webhook URL의 포트만 `8002`로 바꾸면 됨).

## API 키 발급 시 주의사항

- Binance에서 API 키 생성 시 **"Enable Futures" 권한만 활성화**하고 **출금 권한은 절대
  켜지 마세요.**
- 가능하면 IP 화이트리스트를 설정하세요.
- `.env` 파일은 git 저장소에 커밋하지 마세요 (`.gitignore`에 이미 포함됨).

## 참고 문서

- [Binance Futures API 개요](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- [주문 생성](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)
- [헤지모드 전환](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode)
- [트레이딩뷰 웹훅 얼러트 문서](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
