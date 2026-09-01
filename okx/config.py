"""
설정 파일 — OKX TradingView 웹훅 봇.
API 키는 여기 직접 넣지 말고 .env 파일에 저장하세요 (.env.example 참고).
"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class ApiConfig:
    api_key: str = os.getenv("OKX_API_KEY", "")
    api_secret: str = os.getenv("OKX_API_SECRET", "")
    api_passphrase: str = os.getenv("OKX_API_PASSPHRASE", "")
    base_url: str = "https://www.okx.com"
    # live / demo — demo(모의매매)는 OKX 앱/웹의 "Demo trading" 메뉴에서 별도로 발급하는
    # 전용 API 키가 필요함(실전 키 재사용 불가, Binance 테스트넷과 비슷한 제약). 모든 요청에
    # x-simulated-trading: 1 헤더를 추가로 붙여야 함 — okx_client.py가 env에 따라 자동 처리.
    env: str = os.getenv("OKX_ENV", "demo")

    live_trading_confirm: str = os.getenv("LIVE_TRADING_CONFIRM", "")

    @property
    def is_demo(self) -> bool:
        return self.env != "live"


@dataclass
class WebhookConfig:
    shared_secret: str = os.getenv("WEBHOOK_SECRET", "")
    host: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port: int = int(os.getenv("WEBHOOK_PORT", "8003"))


@dataclass
class TelegramConfig:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class TradeConfig:
    # OKX는 심볼 표기가 다른 거래소와 다름 — "BTCUSDT"가 아니라 "BTC-USDT-SWAP"(무기한 스왑).
    symbol: str = os.getenv("TRADE_SYMBOL", "BTC-USDT-SWAP")
    margin_mode: str = os.getenv("MARGIN_MODE", "isolated")  # isolated / cross → mgnMode 그대로
    leverage: int = int(os.getenv("LEVERAGE", "20"))
    order_type: str = "market"

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
            "실전(OKX_ENV=live) + DRY_RUN=false 조합으로 시작하려면 "
            ".env에 LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK 를 정확히 추가해야 합니다. "
            "실수 방지용 안전장치이니, 정말 실전 전환을 의도한 경우에만 추가하세요."
        )
