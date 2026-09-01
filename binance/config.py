"""
설정 파일 — Binance TradingView 웹훅 봇.
API 키는 여기 직접 넣지 말고 .env 파일에 저장하세요 (.env.example 참고).
"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


_BASE_URLS = {
    "live": "https://fapi.binance.com",
    # 테스트넷 — 실전과 완전히 별도의 계정/키 체계. https://testnet.binancefuture.com 에서
    # 별도로 가입하고 그 사이트에서 발급한 테스트넷 전용 API 키를 써야 함 (Bitget/Bybit처럼
    # "실전 키 그대로 base_url만 바꾸면 데모"가 아님 — 주의).
    "testnet": "https://testnet.binancefuture.com",
}


@dataclass
class ApiConfig:
    api_key: str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    # live / testnet — testnet은 반드시 테스트넷 전용 키를 발급받아 써야 함 (위 주석 참고).
    env: str = os.getenv("BINANCE_ENV", "testnet")

    live_trading_confirm: str = os.getenv("LIVE_TRADING_CONFIRM", "")

    @property
    def base_url(self) -> str:
        return _BASE_URLS.get(self.env, _BASE_URLS["live"])

    @property
    def is_demo(self) -> bool:
        return self.env != "live"


@dataclass
class WebhookConfig:
    shared_secret: str = os.getenv("WEBHOOK_SECRET", "")
    host: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port: int = int(os.getenv("WEBHOOK_PORT", "8002"))


@dataclass
class TelegramConfig:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class TradeConfig:
    symbol: str = os.getenv("TRADE_SYMBOL", "BTCUSDT")
    margin_mode: str = os.getenv("MARGIN_MODE", "isolated")  # isolated → ISOLATED, cross → CROSSED
    leverage: int = int(os.getenv("LEVERAGE", "20"))
    order_type: str = "MARKET"

    dry_run: bool = os.getenv("DRY_RUN", "true").strip().lower() != "false"

    @property
    def margin_type_api_value(self) -> str:
        return "ISOLATED" if self.margin_mode.lower() == "isolated" else "CROSSED"


API_CONFIG = ApiConfig()
WEBHOOK_CONFIG = WebhookConfig()
TELEGRAM_CONFIG = TelegramConfig()
TRADE_CONFIG = TradeConfig()


def check_live_trading_safety() -> None:
    """dry_run=False + 실전(env=="live") 조합일 때, LIVE_TRADING_CONFIRM 값이 정확히
    일치하지 않으면 시작을 막는다. 실수로 실거래가 나가는 걸 막기 위한 마지막 안전장치."""
    if TRADE_CONFIG.dry_run:
        return
    if API_CONFIG.is_demo:
        return
    if API_CONFIG.live_trading_confirm != "I_ACCEPT_THE_RISK":
        raise RuntimeError(
            "실전(BINANCE_ENV=live) + DRY_RUN=false 조합으로 시작하려면 "
            ".env에 LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK 를 정확히 추가해야 합니다. "
            "실수 방지용 안전장치이니, 정말 실전 전환을 의도한 경우에만 추가하세요."
        )
