"""
Bybit V5 API 클라이언트 — 서명/요청 담당. 전략 로직은 모르는 얇은 래퍼로 유지할 것.

서명 방식(V5 공식 문서): HMAC-SHA256(secret, timestamp + api_key + recv_window + payload),
결과는 소문자 hex 문자열. GET은 payload=쿼리스트링, POST는 payload=JSON 바디 문자열.
헤더: X-BAPI-API-KEY, X-BAPI-TIMESTAMP, X-BAPI-SIGN, X-BAPI-RECV-WINDOW.
"""

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import requests

from config import ApiConfig

logger = logging.getLogger("bybit_client")

RECV_WINDOW = "5000"


class BybitAPIError(Exception):
    pass


class BybitClient:
    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg

    def _sign(self, payload: str, timestamp: str) -> str:
        raw = f"{timestamp}{self.cfg.api_key}{RECV_WINDOW}{payload}"
        return hmac.new(self.cfg.api_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    def _headers(self, payload: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        return {
            "X-BAPI-API-KEY": self.cfg.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": self._sign(payload, timestamp),
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: dict = None, body: dict = None,
                 auth: bool = True) -> dict:
        url = self.cfg.base_url + path
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {}
        if auth:
            if method == "GET":
                payload = urlencode(params)
                headers = self._headers(payload)
            else:
                payload = json.dumps(body or {})
                headers = self._headers(payload)

        if method == "GET":
            resp = requests.get(url, params=params, headers=headers, timeout=10)
        else:
            resp = requests.post(url, json=body or {}, headers=headers, timeout=10)

        data = resp.json()
        if data.get("retCode") != 0:
            raise BybitAPIError(f"{path} 실패: retCode={data.get('retCode')} "
                                 f"retMsg={data.get('retMsg')} (요청: {params or body})")
        return data.get("result", {})

    # ── 조회 ────────────────────────────────────────────────────────────────
    def get_wallet_balance(self, account_type: str) -> dict:
        return self._request("GET", "/v5/account/wallet-balance", params={"accountType": account_type})

    def get_positions(self, category: str, symbol: str) -> list:
        result = self._request("GET", "/v5/position/list", params={"category": category, "symbol": symbol})
        return result.get("list", [])

    def get_tickers(self, category: str, symbol: str) -> list:
        # 공개 데이터(시세 조회)라 인증 불필요.
        result = self._request("GET", "/v5/market/tickers",
                                params={"category": category, "symbol": symbol}, auth=False)
        return result.get("list", [])

    # ── 계좌 설정 ───────────────────────────────────────────────────────────
    def set_margin_mode(self, mode: str) -> None:
        """ISOLATED_MARGIN / REGULAR_MARGIN(교차). 통합계좌는 심볼별이 아니라 계좌 전체
        단위 설정이라 매 주문마다 부를 필요 없음 — webhook_bot.py가 시작 시 한 번만 호출함."""
        self._request("POST", "/v5/account/set-margin-mode", body={"setMarginMode": mode})

    def set_leverage(self, category: str, symbol: str, buy_leverage: str, sell_leverage: str) -> None:
        self._request("POST", "/v5/position/set-leverage", body={
            "category": category, "symbol": symbol,
            "buyLeverage": buy_leverage, "sellLeverage": sell_leverage,
        })

    def switch_position_mode(self, category: str, symbol: str, mode: int) -> None:
        """mode: 0=원웨이, 3=헤지(양방향). 포지션이 열려있는 상태에서 호출하면 거부될 수 있음 —
        webhook_bot.py는 시작 시 한 번만 시도하고 실패해도(이미 원하는 모드거나 포지션 보유 중)
        경고만 남기고 계속 진행함(계좌가 이미 헤지모드로 세팅되어 있다는 전제)."""
        self._request("POST", "/v5/position/switch-mode",
                       body={"category": category, "symbol": symbol, "mode": mode})

    # ── 주문 ────────────────────────────────────────────────────────────────
    def place_order(self, category: str, symbol: str, side: str, order_type: str, qty: str,
                     position_idx: int, reduce_only: bool, order_link_id: str) -> dict:
        return self._request("POST", "/v5/order/create", body={
            "category": category, "symbol": symbol, "side": side, "orderType": order_type,
            "qty": qty, "positionIdx": position_idx, "reduceOnly": reduce_only,
            "orderLinkId": order_link_id,
        })
