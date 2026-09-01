"""
TradingView 웹훅 자동매매 봇 (Binance) — FastAPI 서버.

플로우:
  트레이딩뷰 얼러트(웹훅 POST) → 시크릿 검증 → comment로 동작 결정 →
  실제 계좌 잔고 기준으로 수량 재계산 → Binance 주문 실행 → 텔레그램으로 결과 통보

⚠️ 수량을 트레이딩뷰 알림값(strategy.order.contracts)에서 그대로 가져오지 않는 이유:
Pine 전략의 수량은 스크립트 자체의 initial_capital(백테스트용 가상 자본)을 기준으로
계산된 값이라, 실제 계좌 잔고와 다르면 주문 크기가 완전히 어긋난다. 그래서:
  - 진입(오픈) 시: comment로 "어떤 종류의 진입인지"만 판단하고, 수량은 실시간 계좌 잔고로 이 봇이 직접 재계산
  - 청산(클로즈) 시: 거래소의 "현재 실제 포지션 크기"를 조회해서 그 비율만큼만 닫음
트레이딩뷰가 보낸 숫자(contracts/position_size)는 로그·대조 검증용으로만 남기고 주문 크기 결정에는 안 씀.

⚠️ 실전 투입 전 필수 확인: 이 파일은 Binance USDⓈ-M Futures 공식 문서를 기준으로 작성했고,
테스트넷 계좌로 아직 실측 검증하지 않았음. get_account/get_position_risk/get_mark_price
응답의 실제 필드명이 아래 코드와 일치하는지 테스트넷 계좌로 먼저 찍어보고 확인할 것.

⚠️ Bitget/Bybit과 다른 점: 헤지모드 청산 주문은 side가 포지션 반대 방향이고(Bybit과 동일),
롱/숏 "장부" 구분은 positionSide(LONG/SHORT)로 함(Bybit의 positionIdx와 같은 역할). reduceOnly
파라미터는 헤지모드에서 아예 보내면 안 됨(거부됨) — positionSide만으로 이미 어느 쪽 포지션을
줄이는지 명확해서 별도 reduceOnly 플래그가 필요/허용되지 않음.
"""

import logging
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from binance_client import BinanceAPIError, BinanceClient
from config import API_CONFIG, TRADE_CONFIG, WEBHOOK_CONFIG, check_live_trading_safety
import telegram_notifier as tg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("webhook_bot")

check_live_trading_safety()

client = BinanceClient(API_CONFIG)
app = FastAPI(title="TradingView Webhook Bot (Binance)")

SYMBOL = TRADE_CONFIG.symbol

# 마진타입/헤지모드는 계좌·심볼 단위 설정이라 매 주문마다 부르지 않고 시작 시 한 번만 시도함.
# 이미 원하는 상태면 -4046/-4059로 조용히 스킵되도록 binance_client.py가 처리함 — 헤지모드는
# 계좌에 이미 세팅돼 있다는 전제로 동작함.
try:
    client.set_margin_type(SYMBOL, TRADE_CONFIG.margin_type_api_value)
except BinanceAPIError as e:
    logger.warning("마진타입 설정 스킵(이미 설정됐거나 포지션 보유 중일 수 있음): %s", e)
try:
    client.set_position_mode(dual_side=True)
except BinanceAPIError as e:
    logger.warning("헤지모드 전환 스킵(이미 헤지모드거나 포지션 보유 중일 수 있음): %s", e)

# ── comment(strategy.entry/close에 넣어둔 값)별 동작 분류 ──────────────────────
# ../bitget/, ../bybit/와 동일한 계약을 그대로 재사용함(같은 트레이딩뷰 얼러트를 여러 거래소
# 봇에 동시에 연결 가능하도록). 전략 쪽 comment 문자열이 바뀌면 이 집합도 같이 바꿀 것.
OPEN_LONG_COMMENTS = {"Long", "Long-Conf"}
OPEN_SHORT_COMMENTS = {"Short", "Short-Conf"}
CONFLUENCE_COMMENTS = {"Long-Conf", "Short-Conf"}

PARTIAL_CLOSE_COMMENTS = {"tphalf"}
PARTIAL_CLOSE_RATIO = 0.5
FULL_CLOSE_COMMENTS = {"tpfull", "ma200dn", "ma200up", "StopLoss", "LongStop", "ShortStop"}

MARGIN_PCT_BASE = 20.0
MARGIN_PCT_CONFLUENCE = 30.0


def _classify_alert(comment: str) -> str:
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
    """헤지모드에서는 롱/숏 포지션이 "동시에" 존재할 수 있음(positionSide별 별도 장부).
    side_hint 없이 첫 번째 포지션을 그냥 쓰면, 반대방향 청산 웹훅과 신규 진입 웹훅의 도착
    순서가 뒤바뀌었을 때 엉뚱한 포지션을 잘못 닫을 수 있음(Bitget 봇에서 실거래 중 실제로
    발생한 사고 — 자세한 내용은 ../bitget/CLAUDE.md 참고, 이 disambiguation 로직 자체는
    거래소/전략과 무관하게 항상 필요함). side_hint("long"/"short")를 주면 그 방향의 포지션만
    찾아서 반환하고, 없으면 size=0으로 안전하게 스킵 처리."""
    positions = client.get_position_risk(SYMBOL)
    matches = [
        {"size": abs(float(p.get("positionAmt", 0) or 0)),
         "side": "long" if p.get("positionSide") == "LONG" else "short"}
        for p in positions
        if p.get("positionSide") in ("LONG", "SHORT") and abs(float(p.get("positionAmt", 0) or 0)) > 0
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
    방향을 판별. action="sell"이면 롱을 파는 것(=롱 청산), action="buy"면 숏을 사서
    커버하는 것(=숏 청산)."""
    if action == "sell":
        return "long"
    if action == "buy":
        return "short"
    return ""


def get_account_equity() -> float:
    acct = client.get_account()
    equity = acct.get("totalMarginBalance")
    if equity is None:
        raise RuntimeError(f"계좌 응답에서 totalMarginBalance 필드를 못 찾음: {acct}")
    return float(equity)


def get_mark_price() -> float:
    data = client.get_mark_price(SYMBOL)
    price = data.get("markPrice")
    if price is None:
        raise RuntimeError(f"{SYMBOL} markPrice를 찾을 수 없음: {data}")
    return float(price)


def compute_open_size(margin_pct: float) -> str:
    """진입 수량(코인 단위) = 계좌 자산 × 진입당비중% × 레버리지 / 현재가."""
    equity = get_account_equity()
    price = get_mark_price()
    notional = equity * margin_pct / 100 * TRADE_CONFIG.leverage
    return f"{notional / price:.6f}"


# ── 주문 실행 ───────────────────────────────────────────────────────────────
def _handle_open(side: str, position_side: str, direction: str, tag: str, alert: TradingViewAlert) -> None:
    margin_pct = MARGIN_PCT_CONFLUENCE if alert.comment in CONFLUENCE_COMMENTS else MARGIN_PCT_BASE
    size = compute_open_size(margin_pct)

    if TRADE_CONFIG.dry_run:
        logger.info("[DRY RUN] open %s %s size=%s (positionSide=%s)", side, SYMBOL, size, position_side)
        tg.notify_order_success(f"{alert.comment} 진입", SYMBOL, direction, size, alert.price, dry_run=True)
        return

    client.set_leverage(SYMBOL, TRADE_CONFIG.leverage)
    result = client.place_order(
        symbol=SYMBOL, side=side, order_type=TRADE_CONFIG.order_type, quantity=size,
        position_side=position_side, client_order_id=f"wh{tag}{int(time.time())}",
    )
    logger.info("진입 주문 성공: %s", result)
    tg.notify_order_success(f"{alert.comment} 진입", SYMBOL, direction, size, alert.price, dry_run=False)


def _handle_close(ratio: float, tag: str, alert: TradingViewAlert) -> None:
    expected_side = _expected_close_side(alert.action)
    position = get_current_position(side_hint=expected_side)
    if position["size"] <= 0:
        logger.warning("청산 신호(%s, action=%s, 기대 방향=%s) 수신했으나 해당 포지션 없음 — 무시",
                        alert.comment, alert.action, expected_side or "?")
        return

    # 청산은 포지션과 반대 방향의 side + 그 포지션의 positionSide 그대로 (reduceOnly는 헤지모드에서
    # 보내면 안 됨 — positionSide만으로 이미 어느 장부를 줄이는지 명확함).
    if position["side"] == "long":
        close_side, position_side, direction = "SELL", "LONG", "Long"
    else:
        close_side, position_side, direction = "BUY", "SHORT", "Short"
    close_size = f"{position['size'] * ratio:.6f}"

    if TRADE_CONFIG.dry_run:
        logger.info("[DRY RUN] close %s %s size=%s (비율 %.0f%%, positionSide=%s)",
                    close_side, SYMBOL, close_size, ratio * 100, position_side)
        tg.notify_order_success(f"{alert.comment} 청산({ratio*100:.0f}%)", SYMBOL, direction,
                                 close_size, alert.price, dry_run=True)
        return

    result = client.place_order(
        symbol=SYMBOL, side=close_side, order_type=TRADE_CONFIG.order_type, quantity=close_size,
        position_side=position_side, client_order_id=f"wh{tag}{int(time.time())}",
    )
    logger.info("청산 주문 성공: %s", result)
    tg.notify_order_success(f"{alert.comment} 청산({ratio*100:.0f}%)", SYMBOL, direction,
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
            _handle_open("BUY", "LONG", "Long", "openlong", alert)
        elif kind == "open_short":
            _handle_open("SELL", "SHORT", "Short", "openshort", alert)
        elif kind == "full_close":
            _handle_close(ratio=1.0, tag="fullclose", alert=alert)
        elif kind == "partial_close":
            _handle_close(ratio=PARTIAL_CLOSE_RATIO, tag="partialclose", alert=alert)
        else:
            logger.warning("알 수 없는 comment 값: '%s' — 무시", alert.comment)
            return {"status": "ignored", "reason": "unknown comment"}
    except BinanceAPIError as e:
        logger.error("Binance API 오류: %s", e)
        tg.notify_order_failure(alert.comment, SYMBOL, str(e))
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("웹훅 처리 중 예외")
        tg.notify_order_failure(alert.comment, SYMBOL, str(e))
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "dry_run": TRADE_CONFIG.dry_run, "env": API_CONFIG.env, "symbol": SYMBOL}


if __name__ == "__main__":
    import uvicorn
    logger.info("TradingView 웹훅 봇(Binance) 시작 — dry_run=%s env=%s symbol=%s",
                TRADE_CONFIG.dry_run, API_CONFIG.env, SYMBOL)
    uvicorn.run(app, host=WEBHOOK_CONFIG.host, port=WEBHOOK_CONFIG.port)
