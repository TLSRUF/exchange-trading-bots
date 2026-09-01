"""
Bitget USDT-M 선물 API 서명/요청 클라이언트.

공식 문서:
- 서명 방식: https://www.bitget.com/api-doc/common/signature
- 주문:      https://www.bitget.com/api-doc/contract/trade/Place-Order
- 계좌:      https://www.bitget.com/api-doc/contract/account/Get-Single-Account
- 레버리지:  https://www.bitget.com/api-doc/contract/account/Change-Leverage
- 캔들:      https://www.bitget.com/api-doc/contract/market/Get-History-Candle-Data
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

import requests

from config import ApiConfig


class BitgetAPIError(Exception):
    def __init__(self, code: str, msg: str, raw: Any = None):
        self.code = code
        self.msg = msg
        self.raw = raw
        super().__init__(f"Bitget API error {code}: {msg}")


class BitgetClient:
    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg
        self.session = requests.Session()

    # ── 서명 ──────────────────────────────────────────────────────
    def _timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, timestamp: str, method: str, request_path: str,
              query_string: str = "", body: str = "") -> str:
        message = timestamp + method.upper() + request_path
        if query_string:
            message += "?" + query_string
        message += body
        mac = hmac.new(self.cfg.api_secret.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, request_path: str,
                 query_string: str = "", body: str = "") -> Dict[str, str]:
        ts = self._timestamp()
        sign = self._sign(ts, method, request_path, query_string, body)
        return {
            "ACCESS-KEY": self.cfg.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.cfg.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    # ── 공통 요청 ─────────────────────────────────────────────────
    def _request(self, method: str, path: str, params: Optional[Dict] = None,
                 body: Optional[Dict] = None, signed: bool = True) -> Any:
        params = params or {}
        query_string = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        url = self.cfg.base_url + path
        if query_string:
            url += "?" + query_string

        headers = {}
        if signed:
            headers = self._headers(method, path, query_string, body_str)

        resp = self.session.request(method, url, headers=headers,
                                     data=body_str if body else None, timeout=15)
        data = resp.json()
        if data.get("code") != "00000":
            raise BitgetAPIError(data.get("code"), data.get("msg"), data)
        return data["data"]

    # ── 공개(비인증) 마켓 데이터 ──────────────────────────────────
    def get_all_tickers(self, product_type: str) -> List[Dict]:
        return self._request("GET", "/api/v2/mix/market/tickers",
                              {"productType": product_type}, signed=False)

    def get_contracts(self, product_type: str, symbol: Optional[str] = None) -> List[Dict]:
        """웹훅 봇 로직에서는 안 쓰지만, 데모 심볼 매핑(config.resolve_trading_symbol)이
        맞는지 확인할 때 쓴 진단용 메서드라 남겨둠 — 새 심볼을 추가할 때 재사용하게 됨."""
        params = {"productType": product_type}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v2/mix/market/contracts", params, signed=False)

    # ── 계좌/포지션 (인증 필요) ───────────────────────────────────
    def get_account(self, symbol: str, product_type: str, margin_coin: str = "USDT") -> Dict:
        params = {"symbol": symbol, "productType": product_type, "marginCoin": margin_coin}
        return self._request("GET", "/api/v2/mix/account/account", params)

    def get_positions(self, product_type: str, margin_coin: str = "USDT") -> List[Dict]:
        params = {"productType": product_type, "marginCoin": margin_coin}
        return self._request("GET", "/api/v2/mix/position/all-position", params)

    def set_leverage(self, symbol: str, product_type: str, leverage: int,
                      margin_coin: str = "USDT", hold_side: Optional[str] = None) -> Dict:
        body = {
            "symbol": symbol, "productType": product_type, "marginCoin": margin_coin,
            "leverage": str(leverage),
        }
        if hold_side:
            body["holdSide"] = hold_side
        return self._request("POST", "/api/v2/mix/account/set-leverage", body=body)

    def set_margin_mode(self, symbol: str, product_type: str, margin_mode: str,
                         margin_coin: str = "USDT") -> Dict:
        body = {"symbol": symbol, "productType": product_type,
                "marginCoin": margin_coin, "marginMode": margin_mode}
        return self._request("POST", "/api/v2/mix/account/set-margin-mode", body=body)

    # ── 주문 ─────────────────────────────────────────────────────
    def place_order(self, symbol: str, product_type: str, margin_mode: str, margin_coin: str,
                     size: str, side: str, order_type: str = "market",
                     price: Optional[str] = None, trade_side: Optional[str] = None,
                     preset_stop_loss_price: Optional[str] = None,
                     preset_take_profit_price: Optional[str] = None,
                     client_oid: Optional[str] = None) -> Dict:
        body = {
            "symbol": symbol, "productType": product_type, "marginMode": margin_mode,
            "marginCoin": margin_coin, "size": size, "side": side, "orderType": order_type,
        }
        if order_type == "limit":
            body["price"] = price
            body["force"] = "gtc"
        if trade_side:
            body["tradeSide"] = trade_side
        if preset_stop_loss_price:
            body["presetStopLossPrice"] = preset_stop_loss_price
        if preset_take_profit_price:
            body["presetStopSurplusPrice"] = preset_take_profit_price
        if client_oid:
            body["clientOid"] = client_oid
        return self._request("POST", "/api/v2/mix/order/place-order", body=body)

    def flash_close_position(self, symbol: str, product_type: str,
                              hold_side: Optional[str] = None) -> Dict:
        body = {"symbol": symbol, "productType": product_type}
        if hold_side:
            body["holdSide"] = hold_side
        return self._request("POST", "/api/v2/mix/order/close-positions", body=body)
