# TradingView 웹훅 자동매매 봇 (Bitget)

**Language:** 한국어 (현재) | [English](./README.en.md)

트레이딩뷰 전략(별도 비공개 Pine Script, 이 저장소에는 포함되지 않음)의 진입/청산 얼러트를
웹훅으로 받아서, Bitget USDT-M 선물로 실제 주문을 내고 텔레그램으로 결과를 알려주는 파이썬
서버입니다.

이 저장소에는 **매매 전략 자체의 로직(진입/청산 조건, 지표, 파라미터)은 포함되어 있지 않습니다.**
여기 있는 건 "얼러트를 받아서 실제 거래소 주문으로 안전하게 변환·실행하는" 실행 계층뿐입니다.

## ⚠️ 먼저 읽어주세요 (리스크 고지)

- 이 코드는 투자 조언이 아니며, 수익을 보장하지 않습니다.
- 선물(레버리지) 거래는 원금 전액 손실 및 청산 위험이 있습니다. 감당 가능한 금액으로만 거래하세요.
- **반드시 아래 순서로 진행하세요: ① DRY_RUN=true로 로그만 확인 → ② 데모 계좌로 실제 주문 흐름
  검증 → ③ 소액 실전.**
- 이 봇은 참고용 도구입니다. 최종 매매 실행과 그 책임은 전적으로 사용자 본인에게 있습니다.

## 전체 흐름

```
트레이딩뷰 (Pine 전략 얼러트)
   │  웹훅 POST (JSON)
   ▼
webhook_bot.py  (FastAPI, 상시 실행되는 서버/VPS)
   │  1. secret 검증
   │  2. comment 값으로 동작 판단 (진입 / 부분청산 / 전량청산)
   │  3. 수량은 트레이딩뷰 알림값을 그대로 안 쓰고, 실시간 계좌 잔고/포지션으로 재계산
   ▼
bitget_client.py → Bitget REST API 주문 실행
   │
   ▼
telegram_notifier.py → 텔레그램으로 성공/실패 결과 통보
```

### 왜 수량을 트레이딩뷰 알림값에서 직접 안 가져오나

Pine 전략의 주문 수량은 스크립트 안의 `initial_capital`(백테스트용 가상 자본)을 기준으로
계산됩니다. 실제 거래소 계좌 잔고가 그 값과 다르면(대부분 다름) 알림에 찍히는 수량을 그대로
주문에 쓰는 순간 포지션 크기가 완전히 어긋납니다. 그래서:

- **진입**: comment로 "어떤 종류의 진입인지"만 받고, 수량은 봇이 실시간 계좌 잔고 기준으로
  직접 계산합니다.
- **청산**: 거래소에서 조회한 "현재 실제 보유 포지션 크기"를 기준으로 얼마를 닫을지 결정합니다
  (전량 또는 부분).

트레이딩뷰가 보낸 `contracts`/`position_size` 값은 로그로만 남기고 실제 주문 크기 결정에는
쓰지 않습니다.

## 폴더 구성

| 파일 | 역할 |
|---|---|
| `config.py` | API/웹훅/텔레그램/거래 설정 (전부 `.env`에서 읽음) |
| `bitget_client.py` | Bitget API 서명/요청 클라이언트 |
| `webhook_bot.py` | 트레이딩뷰 웹훅을 받아 Bitget 주문을 실행하는 FastAPI 서버 (진입점) |
| `telegram_notifier.py` | 텔레그램 알림 전송 (주문 결과가 나온 뒤에 호출) |

## 설치

```bash
pip install -r requirements.txt
cp .env.example .env
```

`.env`를 열어 아래 항목을 채우세요:

- `BITGET_API_KEY` / `BITGET_API_SECRET` / `BITGET_API_PASSPHRASE`
- `WEBHOOK_SECRET` — 아무 문자열이나 길고 무작위하게 (트레이딩뷰 얼러트 JSON에도 동일하게 넣어야 함)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — 없으면 텔레그램 알림만 비활성화되고 나머지는 정상 동작
- `TRADE_SYMBOL`, `MARGIN_MODE`, `LEVERAGE`, `DRY_RUN` — 필요시 조정

## 1단계 — DRY RUN으로 로직만 확인

```bash
python webhook_bot.py
```

`.env`의 `DRY_RUN`이 기본 `true`라서, 웹훅을 받아도 실제 주문은 안 나가고 로그 + 텔레그램(모의
표시)만 찍힙니다. 아래처럼 직접 웹훅을 흉내내서 테스트할 수 있습니다:

```bash
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"<WEBHOOK_SECRET과 동일하게>","symbol":"BTCUSDT.P","action":"buy","contracts":"0.01","comment":"Long","price":"65000"}'
```

## 2단계 — 데모 계좌로 실제 주문 흐름 검증

Bitget은 별도 테스트넷 키가 없습니다. 평소 API 키 그대로 쓰되 `.env`의
`BITGET_PRODUCT_TYPE=SUSDT-FUTURES`(기본값)로 데모 잔고를 사용합니다.

1. `.env`에서 `DRY_RUN=false`로 변경 (productType이 `S`로 시작하는 데모라서
   `LIVE_TRADING_CONFIRM` 없이도 켜짐 — `config.py`의 안전장치 참고).
2. `python webhook_bot.py` 실행 후, 위 `curl` 테스트로 진입 → 부분청산 → 전량청산 순서로
   보내보면서 실제 데모 계좌에 정상 반영되는지 확인.

> 데모 계좌에서는 마진 코인만 바뀌는 게 아니라 심볼 자체도 바뀌는데(`BTCUSDT` →
> `SBTCSUSDT` 식), `config.py`의 `resolve_trading_symbol()`이 자동 처리합니다. `.env`의
> `TRADE_SYMBOL`은 항상 실전 표기 그대로 두면 됩니다.

## 3단계 — 트레이딩뷰 얼러트 연결

1. 전략을 차트에 올리고 전략 탭에서 얼러트 생성.
2. **Webhook URL**: `http://<서버 주소>:8000/webhook/tradingview`
3. **메시지(Message)**에 아래 JSON을 그대로 넣기 (트레이딩뷰 플레이스홀더 사용):

   ```json
   {
     "secret": "<.env의 WEBHOOK_SECRET과 동일하게>",
     "symbol": "{{ticker}}",
     "action": "{{strategy.order.action}}",
     "contracts": "{{strategy.order.contracts}}",
     "position_size": "{{strategy.position_size}}",
     "price": "{{close}}",
     "comment": "{{strategy.order.comment}}",
     "time": "{{time}}"
   }
   ```

4. "주문 발생 시" (Order fills only) 조건으로 얼러트를 만들면 `comment` 필드에 전략이 심어둔
   태그 값이 그대로 들어옵니다. `webhook_bot.py`는 이 `comment` 값으로만 동작을 구분하므로,
   전략 쪽 comment 문자열을 바꾸면 `webhook_bot.py` 상단의 분류 집합도 같이 바꿔야 합니다.

## 4단계 — 실전 전환

1. `.env`의 `BITGET_PRODUCT_TYPE=USDT-FUTURES`로 변경, 실전 API 키 확인.
2. `DRY_RUN=false` + 실전 productType 조합이면 `LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK`를
   명시적으로 넣어야 서버가 켜집니다(실수 방지용 최종 안전장치, `config.py` 참고).
3. 서버가 24시간 상시 실행되어야 알림을 놓치지 않습니다. "이 서버를 어디서/어떻게 계속
   띄워두나"는 [최상위 README의 "서버는 어디서, 어떻게 돌리나요?"](../README.md#서버는-어디서-어떻게-돌리나요)에
   VPS 선택부터 systemd 등록, HTTPS 리버스 프록시까지 정리해뒀습니다. 이 폴더용 systemd
   서비스 예시만 빠르게 보면:

   ```ini
   # /etc/systemd/system/tvbot-bitget.service
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
   sudo systemctl daemon-reload && sudo systemctl enable --now tvbot-bitget
   ```
4. 방화벽(및 클라우드 보안그룹)에서 `WEBHOOK_PORT`(기본 8000)를 트레이딩뷰가 접근 가능하게
   열어야 함 — 또는 위 가이드처럼 Nginx 리버스 프록시로 HTTPS를 앞단에 두고 포트를 직접
   노출하지 않는 방법을 권장.

## API 키 발급 시 주의사항

- Bitget에서 API 키 생성 시 **"선물 거래" 권한만 활성화**하고 **출금 권한은 절대 켜지 마세요.**
- 가능하면 IP 화이트리스트를 설정해 키가 유출되어도 다른 곳에서 사용되지 못하게 하세요.
- `.env` 파일은 git 저장소에 커밋하지 마세요 (`.gitignore`에 이미 포함됨).

## 참고 문서

- [Bitget Futures API 개요](https://www.bitget.com/api-doc/contract/intro)
- [서명 방식](https://www.bitget.com/api-doc/common/signature)
- [주문 API](https://www.bitget.com/api-doc/contract/trade/Place-Order)
- [트레이딩뷰 웹훅 얼러트 문서](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
