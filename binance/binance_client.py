"""
Binance USDⓈ-M 선물(fapi) API 클라이언트 — 서명/요청 담당. 전략 로직은 모르는 얇은
래퍼로 유지할 것.

서명 방식: 모든 요청 파라미터(timestamp, recvWindow 포함)를 쿼리스트링으로 만들고,
HMAC-SHA256(secret, queryString) 결과(hex)를 signature 파라미터로 붙여서 전송.
GET/POST 둘 다 쿼리스트링 방식으로 보냄(Binance futures API는 POST도 바디가 아니라
쿼리스트링 파라미터를 받음). 헤더는 X-MBX-APIKEY 하나만 필요.
"""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests

from config import ApiConfig

logger = logging.getLogger("binance_client")

RECV_WINDOW = 5000

# 계좌 설정 API가 "이미 그 상태"라서 반환하는 에러 코드 — 실패로 취급하지 않고 그냥 넘어감.
_IGNORABLE_CODES = {
    -4046,  # No need to change margin type.
    -4059,  # No need to change position side.
}


class BinanceAPIError(Exception):
    def __init__(self, message: str, code: int = None):
        super().__init__(message)
        self.code = code


class BinanceClient:
    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg

    def _sign(self, query_string: str) -> str:
        return hmac.new(self.cfg.api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict = None, auth: bool = True,
                 ignore_codes: set = frozenset()) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {}
        if auth:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = RECV_WINDOW
            query_string = urlencode(params)
            params["signature"] = self._sign(query_string)
            headers = {"X-MBX-APIKEY": self.cfg.api_key}

        url = self.cfg.base_url + path
        resp = requests.request(method, url, params=params, headers=headers, timeout=10)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise BinanceAPIError(f"{path} 응답을 JSON으로 파싱 못 함: {resp.text[:200]}")

        if isinstance(data, dict) and "code" in data and data.get("code", 0) < 0:
            code = data["code"]
            if code in _IGNORABLE_CODES or code in ignore_codes:
                logger.info("%s: 무시 가능한 응답(code=%s msg=%s)", path, code, data.get("msg"))
                return data
            raise BinanceAPIError(f"{path} 실패: code={code} msg={data.get('msg')} "
                                   f"(요청: {params})", code=code)
        return data

    # ── 조회 ────────────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        return self._request("GET", "/fapi/v2/account")

    def get_position_risk(self, symbol: str) -> list:
        result = self._request("GET", "/fapi/v2/positionRisk", params={"symbol": symbol})
        return result if isinstance(result, list) else []

    def get_mark_price(self, symbol: str) -> dict:
        # 공개 데이터(시세 조회)라 인증 불필요.
        return self._request("GET", "/fapi/v1/premiumIndex", params={"symbol": symbol}, auth=False)

    # ── 계좌 설정 ───────────────────────────────────────────────────────────
    def set_margin_type(self, symbol: str, margin_type: str) -> None:
        self._request("POST", "/fapi/v1/marginType", params={"symbol": symbol, "marginType": margin_type})

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self._request("POST", "/fapi/v1/leverage", params={"symbol": symbol, "leverage": leverage})

    def set_position_mode(self, dual_side: bool) -> None:
        """dual_side=True → 헤지모드(양방향 포지션). 이미 원하는 모드면 -4059로 조용히 스킵됨."""
        self._request("POST", "/fapi/v1/positionSide/dual",
                       params={"dualSidePosition": "true" if dual_side else "false"})

    # ── 주문 ────────────────────────────────────────────────────────────────
    def place_order(self, symbol: str, side: str, order_type: str, quantity: str,
                     position_side: str, client_order_id: str) -> dict:
        return self._request("POST", "/fapi/v1/order", params={
            "symbol": symbol, "side": side, "type": order_type, "quantity": quantity,
            "positionSide": position_side, "newClientOrderId": client_order_id,
        })
