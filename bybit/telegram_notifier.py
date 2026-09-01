"""
텔레그램 알림 전송 — 거래 실행 "이후" 결과(성공/실패, 체결가 등)를 알리는 용도.
신호 수신 시점이 아니라 실제 거래소 응답을 받은 뒤에 호출해야 의미가 있음 (webhook_bot.py 참고).

봇 토큰 발급: 텔레그램에서 @BotFather 검색 → /newbot
chat_id 확인: 봇과 대화 시작 후 https://api.telegram.org/bot<TOKEN>/getUpdates 호출해서 chat.id 확인
"""

import logging

import requests

from config import TELEGRAM_CONFIG

logger = logging.getLogger("telegram_notifier")


def send_message(text: str) -> bool:
    """텔레그램으로 메시지 전송. 토큰/chat_id 미설정 시 조용히 스킵(False 반환)하고 로그만 남김 —
    텔레그램 전송 실패가 거래 로직 자체를 막으면 안 되므로 예외를 던지지 않음."""
    if not TELEGRAM_CONFIG.enabled:
        logger.warning("텔레그램 미설정(TELEGRAM_BOT_TOKEN/CHAT_ID) — 알림 스킵: %s", text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_CONFIG.bot_token}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CONFIG.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error("텔레그램 전송 실패 응답: %s", data)
            return False
        return True
    except requests.RequestException as e:
        logger.error("텔레그램 전송 중 네트워크 오류: %s", e)
        return False


# direction은 거래소 API의 원본 side 값이 아니라 webhook_bot.py가 판단한 논리적 방향
# ("Long"/"Short")을 그대로 받음 — 헤지모드에서 청산 주문의 실제 side(buy/sell)는 거래소마다
# 의미가 달라서(Bitget: side=포지션 방향, Bybit/Binance/OKX: side=실제 체결 방향) 원본 side만
# 보고는 Long/Short을 안전하게 못 뽑아냄. 항상 호출부에서 명시적으로 넘길 것.
def notify_order_success(action_desc: str, symbol: str, direction: str, size: str,
                          price: str = "", dry_run: bool = False) -> None:
    prefix = "🧪 [모의]" if dry_run else "✅ [실거래]"
    lines = [
        f"{prefix} <b>{action_desc}</b>",
        f"심볼: {symbol}",
        f"방향: {direction}",
        f"수량: {size}",
    ]
    if price:
        lines.append(f"가격: {price}")
    send_message("\n".join(lines))


def notify_order_failure(action_desc: str, symbol: str, error: str) -> None:
    send_message(f"🚨 <b>주문 실패</b>\n동작: {action_desc}\n심볼: {symbol}\n오류: {error}")


def notify_webhook_rejected(reason: str) -> None:
    send_message(f"⚠️ <b>웹훅 거부됨</b>\n사유: {reason}")
