"""
OKX V5 API 클라이언트 — 서명/요청 담당. 전략 로직은 모르는 얇은 래퍼로 유지할 것.

서명 방식(V5 공식 문서): prehash = timestamp(ISO8601 밀리초) + method(대문자) + requestPath
(+쿼리스트링, GET인 경우) + body(JSON 문자열, GET은 빈 문자열). HMAC-SHA256 후 Base64 인코딩.
헤더: OK-ACCESS-KEY, OK-ACCESS-SIGN, OK-ACCESS-TIMESTAMP, OK-ACCESS-PASSPHRASE.
데모(모의매매) 계좌는 추가로 x-simulated-trading: 1 헤더가 필요함.
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

import requests

from config import ApiConfig

logger = logging.getLogger("okx_client")


class OkxAPIError(Exception):
    pass


class OkxClient:
    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg

    def _timestamp(self) -> str:
        # OKX가 요구하는 형식: 2020-12-08T09:08:57.715Z (밀리초, Z 고정)
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"

    def _sign(self, prehash: str) -> str:
        mac = hmac.new(self.cfg.api_secret.encode(), prehash.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, request_path: str, body_str: str) -> dict:
        timestamp = self._timestamp()
        prehash = f"{timestamp}{method}{request_path}{body_str}"
        headers = {
            "OK-ACCESS-KEY": self.cfg.api_key,
            "OK-ACCESS-SIGN": self._sign(prehash),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.cfg.api_passphrase,
            "Content-Type": "application/json",
        }
        if self.cfg.is_demo:
            headers["x-simulated-trading"] = "1"
        return headers

    def _request(self, method: str, path: str, params: dict = None, body: dict = None,
                 auth: bool = True) -> list:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        body_str = json.dumps(body) if body else ""

        headers = {}
        if auth:
            headers = self._headers(method, path + query, body_str)

        url = self.cfg.base_url + path + query
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, data=body_str, headers=headers, timeout=10)

        data = resp.json()
        if data.get("code") != "0":
            raise OkxAPIError(f"{path} 실패: code={data.get('code')} msg={data.get('msg')} "
                               f"(요청: {params or body})")
        return data.get("data", [])

    # ── 조회 ────────────────────────────────────────────────────────────────
    def get_balance(self) -> list:
        return self._request("GET", "/api/v5/account/balance")

    def get_positions(self, inst_type: str, inst_id: str) -> list:
        return self._request("GET", "/api/v5/account/positions",
                              params={"instType": inst_type, "instId": inst_id})

    def get_mark_price(self, inst_type: str, inst_id: str) -> list:
        # 공개 데이터(시세 조회)라 인증 불필요.
        return self._request("GET", "/api/v5/public/mark-price",
                              params={"instType": inst_type, "instId": inst_id}, auth=False)

    def get_instrument(self, inst_type: str, inst_id: str) -> list:
        """계약 스펙(계약당 코인 수량 ctVal, 최소 주문단위 lotSz 등). 공개 데이터라 인증 불필요.
        OKX 스왑 주문의 sz는 코인 수량이 아니라 "계약 개수"라서 이 값으로 환산해야 함."""
        return self._request("GET", "/api/v5/public/instruments",
                              params={"instType": inst_type, "instId": inst_id}, auth=False)

    # ── 계좌 설정 ───────────────────────────────────────────────────────────
    def set_position_mode(self, pos_mode: str) -> None:
        """long_short_mode(헤지) / net_mode. 계좌 전체 단위 설정 — webhook_bot.py가 시작 시
        한 번만 호출함. 포지션이 열려있으면 거부될 수 있음."""
        self._request("POST", "/api/v5/account/set-position-mode", body={"posMode": pos_mode})

    def set_leverage(self, inst_id: str, lever: str, mgn_mode: str, pos_side: str = None) -> None:
        body = {"instId": inst_id, "lever": lever, "mgnMode": mgn_mode}
        if pos_side:
            body["posSide"] = pos_side
        self._request("POST", "/api/v5/account/set-leverage", body=body)

    # ── 주문 ────────────────────────────────────────────────────────────────
    def place_order(self, inst_id: str, td_mode: str, side: str, order_type: str, sz: str,
                     pos_side: str, client_order_id: str) -> list:
        return self._request("POST", "/api/v5/trade/order", body={
            "instId": inst_id, "tdMode": td_mode, "side": side, "ordType": order_type,
            "sz": sz, "posSide": pos_side, "clOrdId": client_order_id,
        })


def round_to_lot(qty: float, lot_sz: str) -> str:
    """qty(계약 개수, float)를 lotSz(계약 단위)의 배수로 내림 처리해서 문자열로 반환."""
    lot = Decimal(lot_sz)
    steps = (Decimal(str(qty)) / lot).to_integral_value(rounding=ROUND_DOWN)
    return str(steps * lot)
