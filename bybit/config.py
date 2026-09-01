"""
설정 파일 — Bybit TradingView 웹훅 봇.
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
    "live": "https://api.bybit.com",
    # 테스트넷 — 실전과 별도의 테스트넷 전용 API 키 필요 (https://testnet.bybit.com 에서 발급).
    "testnet": "https://api-testnet.bybit.com",
    # 데모 트레이딩 — 실전 API 키 그대로 쓰되 이 base_url로 호출하면 가상자금 계좌로 감
    # (Bitget의 productType=SUSDT-FUTURES 방식과 동등한 개념). 권장 시작점.
    "demo": "https://api-demo.bybit.com",
}


@dataclass
class ApiConfig:
    api_key: str = os.getenv("BYBIT_API_KEY", "")
    api_secret: str = os.getenv("BYBIT_API_SECRET", "")
    # live / testnet / demo — testnet은 별도 키 필요, demo는 실전 키 그대로 사용 가능.
    env: str = os.getenv("BYBIT_ENV", "demo")
    account_type: str = "UNIFIED"  # Bybit 통합계좌(Unified Trading Account) 고정값

    # 실전(env=="live") + dry_run=False 조합으로 봇을 켜려면
    # 이 값이 정확히 "I_ACCEPT_THE_RISK"와 일치해야 함 (webhook_bot.py의 안전장치 참고).
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
    port: int = int(os.getenv("WEBHOOK_PORT", "8001"))


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
    category: str = "linear"  # USDT 무기한 선물 고정값
    # ISOLATED_MARGIN / REGULAR_MARGIN(교차) — Bybit 통합계좌는 이게 계좌 전체 단위 설정이라
    # (심볼별 아님), config.py가 아니라 webhook_bot.py 시작 시 한 번만 적용함.
    margin_mode: str = os.getenv("MARGIN_MODE", "isolated")
    leverage: int = int(os.getenv("LEVERAGE", "20"))
    order_type: str = "Market"

    dry_run: bool = os.getenv("DRY_RUN", "true").strip().lower() != "false"


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
            "실전(BYBIT_ENV=live) + DRY_RUN=false 조합으로 시작하려면 "
            ".env에 LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK 를 정확히 추가해야 합니다. "
            "실수 방지용 안전장치이니, 정말 실전 전환을 의도한 경우에만 추가하세요."
        )
