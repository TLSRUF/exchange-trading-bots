"""
설정 파일 — TradingView 웹훅 자동매매 봇.
API 키/토큰은 여기 직접 넣지 말고 .env 파일에 저장하세요 (.env.example 참고).
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
    api_key: str = os.getenv("BITGET_API_KEY", "")
    api_secret: str = os.getenv("BITGET_API_SECRET", "")
    api_passphrase: str = os.getenv("BITGET_API_PASSPHRASE", "")
    base_url: str = "https://api.bitget.com"
    # 실전 = "USDT-FUTURES", 데모(모의투자, 권장 시작점) = "SUSDT-FUTURES"
    # Bitget은 별도 테스트넷 키가 필요 없음 — 평소 API 키 그대로 productType만 바꿔서 호출.
    product_type: str = os.getenv("BITGET_PRODUCT_TYPE", "SUSDT-FUTURES")

    # 실전(productType이 "S"로 시작하지 않음) + dry_run=False 조합으로 봇을 켜려면
    # 이 값이 정확히 "I_ACCEPT_THE_RISK"와 일치해야 함 (webhook_bot.py의 안전장치 참고).
    live_trading_confirm: str = os.getenv("LIVE_TRADING_CONFIRM", "")

    @property
    def margin_coin(self) -> str:
        """productType에 대응하는 증거금 코인. 데모는 실코인 대신 S접두 데모코인을 씀."""
        pt = self.product_type.upper()
        return {
            "USDT-FUTURES": "USDT", "SUSDT-FUTURES": "SUSDT",
            "USDC-FUTURES": "USDC", "SUSDC-FUTURES": "SUSDC",
        }.get(pt, "USDT")

    @property
    def is_demo(self) -> bool:
        return self.product_type.upper().startswith("S")


@dataclass
class WebhookConfig:
    # 트레이딩뷰 얼러트 JSON 메시지 안에 이 값을 그대로 넣어서 보내야 함 — 없거나 틀리면 요청 거부.
    # 트레이딩뷰 웹훅은 기본적으로 인증이 없어서, 이 값이 없으면 URL만 아는 누구나 주문을 낼 수 있음.
    shared_secret: str = os.getenv("WEBHOOK_SECRET", "")
    host: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port: int = int(os.getenv("WEBHOOK_PORT", "8000"))


@dataclass
class TelegramConfig:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class TradeConfig:
    # 트레이딩뷰 {{ticker}}가 "BTCUSDT.P" 같은 형태로 올 수 있어서, 실제 주문은 이 값(Bitget 표기)을
    # 우선 사용하고 얼러트의 symbol은 로그/검증용으로만 참고함 (심볼 여러 개 굴릴 땐 매핑 로직 확장 필요).
    symbol: str = os.getenv("TRADE_SYMBOL", "BTCUSDT")
    margin_mode: str = os.getenv("MARGIN_MODE", "isolated")  # isolated 권장 — 한 종목 손실이 전체 계좌로 전이 안 됨
    # 기본값은 페어링된 Pine 전략의 leverage 인풋과 맞춰둔 것 — 전략 쪽 값을 바꾸면 여기도 같이 바꿀 것.
    leverage: int = int(os.getenv("LEVERAGE", "20"))
    order_type: str = "market"  # 신호 도착 즉시 체결이 목적이라 시장가로 고정

    # 기본값 True(모의) — 실제 주문을 내려면 .env에서 명시적으로 DRY_RUN=false 로 바꿔야 함.
    dry_run: bool = os.getenv("DRY_RUN", "true").strip().lower() != "false"


API_CONFIG = ApiConfig()
WEBHOOK_CONFIG = WebhookConfig()
TELEGRAM_CONFIG = TelegramConfig()
TRADE_CONFIG = TradeConfig()


def resolve_trading_symbol(symbol: str, product_type: str) -> str:
    """실전 심볼(예: BTCUSDT)을 productType에 맞는 실제 거래소 심볼로 변환.

    데모(productType이 "S"로 시작, 예: SUSDT-FUTURES)에서는 Bitget이 마진 코인만 SUSDT로 바뀌는 게
    아니라 심볼 자체도 별도 데모 전용 이름을 씀: BTCUSDT(베이스 BTC + 쿼트 USDT) →
    SBTCSUSDT(S+베이스 + S+쿼트). 이 변환 없이 실전 심볼을 데모 productType에 그대로 쓰면
    "does not support ... as margin" 류의 API 에러가 남 (get_contracts로 실측 확인함).
    이미 "S"로 시작하는 심볼(사용자가 직접 데모 심볼을 넣은 경우)은 그대로 둔다.
    """
    if not product_type.upper().startswith("S"):
        return symbol
    if symbol.upper().startswith("S"):
        return symbol
    if symbol.upper().endswith("USDT"):
        base = symbol[:-4]
        return f"S{base}SUSDT"
    raise ValueError(f"데모 심볼 변환 규칙을 모르는 심볼: {symbol} (USDT로 끝나는 심볼만 지원)")


def check_live_trading_safety() -> None:
    """dry_run=False + 실전 productType 조합일 때, LIVE_TRADING_CONFIRM 값이 정확히
    일치하지 않으면 시작을 막는다. 실수로 실거래가 나가는 걸 막기 위한 마지막 안전장치."""
    if TRADE_CONFIG.dry_run:
        return
    if API_CONFIG.is_demo:
        return
    if API_CONFIG.live_trading_confirm != "I_ACCEPT_THE_RISK":
        raise RuntimeError(
            "실전(productType=USDT-FUTURES) + DRY_RUN=false 조합으로 시작하려면 "
            ".env에 LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK 를 정확히 추가해야 합니다. "
            "실수 방지용 안전장치이니, 정말 실전 전환을 의도한 경우에만 추가하세요."
        )
