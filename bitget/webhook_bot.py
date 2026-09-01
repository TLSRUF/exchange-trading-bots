"""
TradingView 웹훅 자동매매 봇 — FastAPI 서버.

플로우:
  트레이딩뷰 얼러트(웹훅 POST) → 시크릿 검증 → comment로 동작 결정 →
  실제 계좌 잔고 기준으로 수량 재계산 → Bitget 주문 실행 → 텔레그램으로 결과 통보

⚠️ 수량을 트레이딩뷰 알림값(strategy.order.contracts)에서 그대로 가져오지 않는 이유:
Pine 전략의 수량은 스크립트 자체의 initial_capital(백테스트용 가상 자본, 기본 10000)을 기준으로
계산된 값이라, 실제 Bitget 계좌 잔고와 다르면 주문 크기가 완전히 어긋난다. 그래서:
  - 진입(오픈) 시: comment로 "몇 % 진입"인지만 판단하고, 수량은 실시간 계좌 잔고로 이 봇이 직접 재계산
  - 청산(클로즈) 시: 거래소의 "현재 실제 포지션 크기"를 조회해서 그 비율만큼만 닫음
트레이딩뷰가 보낸 숫자(contracts/position_size)는 로그·대조 검증용으로만 남기고 주문 크기 결정에는 안 씀.

⚠️ 실전 투입 전 필수 확인: get_account()/get_positions()/get_all_tickers() 응답의 실제 필드명
(accountEquity, holdSide, total, lastPr 등)을 데모(SUSDT-FUTURES) 계정으로 한 번 찍어보고
아래 코드의 필드명과 일치하는지 확인할 것 — 거래소 API 응답 스키마는 문서와 실제가 다를 수 있음.
"""

import logging
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from bitget_client import BitgetAPIError, BitgetClient
from config import (API_CONFIG, TRADE_CONFIG, WEBHOOK_CONFIG,
                     check_live_trading_safety, resolve_trading_symbol)
import telegram_notifier as tg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("webhook_bot")

check_live_trading_safety()

client = BitgetClient(API_CONFIG)
app = FastAPI(title="TradingView Webhook Bot")

# TRADE_CONFIG.symbol(예: BTCUSDT)은 사용자가 설정하는 "논리적" 심볼이고, 실제 거래소 API에는
# productType에 맞게 변환된 심볼(데모는 SBTCSUSDT 식)을 써야 함 — config.resolve_trading_symbol 참고.
SYMBOL = resolve_trading_symbol(TRADE_CONFIG.symbol, API_CONFIG.product_type)
if SYMBOL != TRADE_CONFIG.symbol:
    logger.info("데모 심볼 변환: %s → %s", TRADE_CONFIG.symbol, SYMBOL)

# ── comment(strategy.entry/close에 넣어둔 값)별 동작 분류 ──────────────────────
# 이 대응관계는 페어링된(비공개) Pine 전략이 실제로 내보내는 comment= 문자열과 정확히
# 일치해야 함 — 전략 쪽 comment 문자열이 바뀌면 이 집합도 같이 바꿀 것. 의미:
#   진입: 기본 마진 티어 태그 또는 "-Conf" 접미사가 붙은 사이즈업 티어 태그
#   청산: 부분청산 태그(매번 "그 시점 남은 포지션의 고정 비율만큼") / 전량청산 태그
#     (익절 마지막 단계·긴급청산·손절 등 여러 이벤트가 전량청산으로 묶여 들어옴 — 일부는
#     같은 이벤트의 동의어: comment 미지정 시 Pine이 주문 id로 폴백하는 값이라, 명시적
#     comment와 id-폴백 값을 둘 다 지원해서 어느 버전이 얼럿을 쏘든 안전하게 함)
OPEN_LONG_COMMENTS = {"Long", "Long-Conf"}
OPEN_SHORT_COMMENTS = {"Short", "Short-Conf"}
CONFLUENCE_COMMENTS = {"Long-Conf", "Short-Conf"}  # 사이즈업 티어 대상 진입

PARTIAL_CLOSE_COMMENTS = {"tphalf"}
PARTIAL_CLOSE_RATIO = 0.5
FULL_CLOSE_COMMENTS = {"tpfull", "ma200dn", "ma200up", "StopLoss", "LongStop", "ShortStop"}

# 아래 두 값은 페어링된 Pine 전략의 사이징 인풋 기본값과 맞춰둔 것 — 전략 쪽 값을 바꾸면 여기도 같이 바꿀 것.
MARGIN_PCT_BASE = 20.0        # 기본 진입 시드 비중(%)
MARGIN_PCT_CONFLUENCE = 30.0  # 사이즈업 티어 시드 비중(%)


def _classify_alert(comment: str) -> str:
    """comment 문자열로 얼러트 종류 판별: open_long / open_short / partial_close / full_close / unknown."""
    if comment in OPEN_LONG_COMMENTS:
        return "open_long"
    if comment in OPEN_SHORT_COMMENTS:
        return "open_short"
    if comment in FULL_CLOSE_COMMENTS:
        return "full_close"
    if comment in PARTIAL_CLOSE_COMMENTS:
        return "partial_close"
    return "unknown"


class TradingViewAlert(BaseModel):
    secret: str
    symbol: str = ""
    action: str = ""
    contracts: str = ""
    position_size: str = ""
    price: str = ""
    comment: str = ""
    time: str = ""


# ── 거래소 조회 헬퍼 ────────────────────────────────────────────────────────
def get_current_position(side_hint: str = "") -> dict:
    """현재 심볼 포지션 정보. 없으면 size=0인 빈 dict 형태로 반환.

    ⚠️ 헤지모드(posMode=hedge_mode)에서는 롱/숏 포지션이 "동시에" 열려있을 수 있음 —
    예를 들어 반대방향 청산 웹훅과 신규 진입 웹훅 두 개가 트레이딩뷰의 Pine 실행 순서(청산
    먼저 → 진입 나중)와 다르게 도착하면(네트워크 지연 등, 순서 보장 없음), 진입이 먼저
    처리돼서 "새 포지션"과 "아직 안 닫힌 기존 포지션"이 한 심볼에 동시에 존재하게 됨.
    이 상태에서 side_hint 없이 그냥 첫 번째로 찾은 포지션을 반환하면, 청산 웹훅이 방금 새로
    연 포지션을 잘못 닫아버리고 정작 닫아야 했던 기존 포지션은 그대로 남는 사고가 실제로 발생함
    (실거래 중 실제로 확인된 사고: 신규 진입 직후 반대방향 청산 웹훅이 방금 연 롱을
    닫아버리고, 원래 닫혔어야 할 숏은 살아있었음 — 이 disambiguation 로직 자체는 comment
    문자열과 무관해서 전략을 교체해도 그대로 유효함). side_hint
    ("long"/"short")를 주면 그 방향의 포지션만 찾아서 반환하고, 없으면 size=0으로 안전하게
    스킵 처리(엉뚱한 반대쪽을 잘못 닫지 않음)."""
    positions = client.get_positions(API_CONFIG.product_type, API_CONFIG.margin_coin)
    matches = [
        {"size": float(p.get("total", 0) or 0), "side": p.get("holdSide", "")}
        for p in positions
        if p.get("symbol") == SYMBOL and float(p.get("total", 0) or 0) > 0
    ]
    if not matches:
        return {"size": 0.0, "side": ""}
    if not side_hint:
        return matches[0]
    for m in matches:
        if m["side"] == side_hint:
            return m
    logger.warning("청산 대상(%s) 포지션을 못 찾음 — 실제 보유 중: %s",
                    side_hint, [(m["side"], m["size"]) for m in matches])
    return {"size": 0.0, "side": ""}


def _expected_close_side(action: str) -> str:
    """알림의 action(트레이딩뷰 {{strategy.order.action}}, buy/sell)으로 청산 대상 포지션의
    holdSide를 판별. 청산 주문에서 action="sell"이면 롱을 파는 것(=롱 청산),
    action="buy"면 숏을 사서 커버하는 것(=숏 청산). 그 순간의 계좌 상태를 추측하지 않고
    알림 자체로 어느 쪽을 닫을지 확정할 수 있어서, 웹훅 도착 순서가 뒤바뀌어도 안전함."""
    if action == "sell":
        return "long"
    if action == "buy":
        return "short"
    return ""


def get_account_equity() -> float:
    acct = client.get_account(SYMBOL, API_CONFIG.product_type, API_CONFIG.margin_coin)
    equity = acct.get("accountEquity") or acct.get("usdtEquity")
    if equity is None:
        raise RuntimeError(f"계좌 응답에서 자산 필드를 못 찾음: {acct}")
    return float(equity)


def get_mark_price() -> float:
    tickers = client.get_all_tickers(API_CONFIG.product_type)
    for t in tickers:
        if t.get("symbol") == SYMBOL:
            price = t.get("lastPr") or t.get("markPrice")
            if price is not None:
                return float(price)
    raise RuntimeError(f"{SYMBOL} 시세를 찾을 수 없음")


def compute_open_size(margin_pct: float) -> str:
    """진입 수량(코인 단위) = 계좌 자산 × 진입당비중% × 레버리지 / 현재가."""
    equity = get_account_equity()
    price = get_mark_price()
    notional = equity * margin_pct / 100 * TRADE_CONFIG.leverage
    return f"{notional / price:.6f}"


# ── 주문 실행 ───────────────────────────────────────────────────────────────
# clientOid는 Bitget 규정상 영숫자 조합만 허용됨(1~40자). 현재 전략의 comment 자체는 전부
# 영문 고정 태그("Long", "tphalf", "ma200dn" 등)라 그대로 써도 되지만, 분류 결과(kind)로
# 만든 별도 태그를 쓰면 향후 comment 문자열이 바뀌어도(예: 한글 포함 문자열로 변경) clientOid
# 규칙이 안전하게 유지됨 — 알림 메시지에는 원본 comment를 그대로 노출.
def _handle_open(side: str, tag: str, alert: TradingViewAlert) -> None:
    margin_pct = MARGIN_PCT_CONFLUENCE if alert.comment in CONFLUENCE_COMMENTS else MARGIN_PCT_BASE
    size = compute_open_size(margin_pct)

    if TRADE_CONFIG.dry_run:
        logger.info("[DRY RUN] open %s %s size=%s", side, SYMBOL, size)
        tg.notify_order_success(f"{alert.comment} 진입", SYMBOL, side, size, alert.price, dry_run=True)
        return

    client.set_margin_mode(SYMBOL, API_CONFIG.product_type,
                            TRADE_CONFIG.margin_mode, API_CONFIG.margin_coin)
    client.set_leverage(SYMBOL, API_CONFIG.product_type,
                         TRADE_CONFIG.leverage, API_CONFIG.margin_coin)
    result = client.place_order(
        symbol=SYMBOL, product_type=API_CONFIG.product_type,
        margin_mode=TRADE_CONFIG.margin_mode, margin_coin=API_CONFIG.margin_coin,
        size=size, side=side, order_type=TRADE_CONFIG.order_type, trade_side="open",
        client_oid=f"wh{tag}{int(time.time())}",
    )
    logger.info("진입 주문 성공: %s", result)
    tg.notify_order_success(f"{alert.comment} 진입", SYMBOL, side, size, alert.price, dry_run=False)


def _handle_close(ratio: float, tag: str, alert: TradingViewAlert) -> None:
    expected_side = _expected_close_side(alert.action)
    position = get_current_position(side_hint=expected_side)
    if position["size"] <= 0:
        logger.warning("청산 신호(%s, action=%s, 기대 방향=%s) 수신했으나 해당 포지션 없음 — 무시",
                        alert.comment, alert.action, expected_side or "?")
        return

    # ⚠️ Bitget 헤지모드(posMode=hedge_mode)에서는 종가(close) 주문의 side가 "반대 방향"이 아니라
    # "포지션과 같은 방향"이어야 함 — 롱 청산 = side buy + tradeSide close, 숏 청산 = side sell +
    # tradeSide close (실측 확인: side를 반대로 넣으면 "No position to close" 에러가 남).
    close_side = "buy" if position["side"] == "long" else "sell"
    close_size = f"{position['size'] * ratio:.6f}"

    if TRADE_CONFIG.dry_run:
        logger.info("[DRY RUN] close %s %s size=%s (비율 %.0f%%)", close_side, SYMBOL, close_size, ratio * 100)
        tg.notify_order_success(f"{alert.comment} 청산({ratio*100:.0f}%)", SYMBOL, close_side,
                                 close_size, alert.price, dry_run=True)
        return

    result = client.place_order(
        symbol=SYMBOL, product_type=API_CONFIG.product_type,
        margin_mode=TRADE_CONFIG.margin_mode, margin_coin=API_CONFIG.margin_coin,
        size=close_size, side=close_side, order_type=TRADE_CONFIG.order_type, trade_side="close",
        client_oid=f"wh{tag}{int(time.time())}",
    )
    logger.info("청산 주문 성공: %s", result)
    tg.notify_order_success(f"{alert.comment} 청산({ratio*100:.0f}%)", SYMBOL, close_side,
                             close_size, alert.price, dry_run=False)


# ── 웹훅 엔드포인트 ─────────────────────────────────────────────────────────
@app.post("/webhook/tradingview")
async def tradingview_webhook(alert: TradingViewAlert):
    if not WEBHOOK_CONFIG.shared_secret or alert.secret != WEBHOOK_CONFIG.shared_secret:
        logger.warning("잘못된 시크릿으로 웹훅 요청 수신 — 거부")
        tg.notify_webhook_rejected("시크릿 불일치 또는 미설정")
        raise HTTPException(status_code=401, detail="invalid secret")

    logger.info("웹훅 수신: comment=%s action=%s contracts=%s position_size=%s",
                alert.comment, alert.action, alert.contracts, alert.position_size)

    try:
        kind = _classify_alert(alert.comment)
        if kind == "open_long":
            _handle_open("buy", "openlong", alert)
        elif kind == "open_short":
            _handle_open("sell", "openshort", alert)
        elif kind == "full_close":
            _handle_close(ratio=1.0, tag="fullclose", alert=alert)
        elif kind == "partial_close":
            _handle_close(ratio=PARTIAL_CLOSE_RATIO, tag="partialclose", alert=alert)
        else:
            logger.warning("알 수 없는 comment 값: '%s' — 무시", alert.comment)
            return {"status": "ignored", "reason": "unknown comment"}
    except BitgetAPIError as e:
        logger.error("Bitget API 오류: %s", e)
        tg.notify_order_failure(alert.comment, SYMBOL, str(e))
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("웹훅 처리 중 예외")
        tg.notify_order_failure(alert.comment, SYMBOL, str(e))
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "dry_run": TRADE_CONFIG.dry_run,
            "product_type": API_CONFIG.product_type, "symbol": SYMBOL}


if __name__ == "__main__":
    import uvicorn
    logger.info("TradingView 웹훅 봇 시작 — dry_run=%s productType=%s symbol=%s",
                TRADE_CONFIG.dry_run, API_CONFIG.product_type, SYMBOL)
    uvicorn.run(app, host=WEBHOOK_CONFIG.host, port=WEBHOOK_CONFIG.port)
