"""
alerts/telegram_bot.py
Tier 5: Alert Dispatcher & Visual Terminal Card Formatter
- Gửi thông báo Telegram Bot có cấu trúc thẻ trực quan kèm Inline Keyboard
- Hiển thị Terminal Visual Card chuẩn mực với ANSI Color & Box Drawing
- Tích hợp ghi log và kiểm soát cảnh báo
"""

import sys
import json
import logging
from typing import Dict, Any, Optional
import requests

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class Fore:
        RED = "\033[91m"
        GREEN = "\033[92m"
        YELLOW = "\033[93m"
        BLUE = "\033[94m"
        MAGENTA = "\033[95m"
        CYAN = "\033[96m"
        WHITE = "\033[97m"
        RESET = "\033[0m"
    class Style:
        BRIGHT = "\033[1m"
        RESET_ALL = "\033[0m"

logger = logging.getLogger("AlertDispatcher")


class AlertDispatcher:
    """
    Điều phối cảnh báo đa kênh: Telegram Bot + Rich Terminal Card UI.
    """
    def __init__(
        self,
        telegram_enabled: bool = False,
        bot_token: str = "",
        chat_id: str = "",
        enable_color: bool = True
    ):
        self.telegram_enabled = telegram_enabled and bool(bot_token) and bool(chat_id)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enable_color = enable_color

    def format_telegram_message(
        self,
        signal_id: int,
        symbol: str,
        proposal: Dict[str, Any],
        ai_result: Dict[str, Any]
    ) -> str:
        """Định dạng bản tin Telegram HTML chuẩn giao dịch"""
        action = proposal.get("action", "BUY_LIMIT")
        entry = proposal.get("entry_price", 0)
        sl = proposal.get("stop_loss", 0)
        tp = proposal.get("take_profit", 0)
        size = proposal.get("position_size", 0)
        risk_usd = proposal.get("risk_amount_usd", 2.0)
        rr = proposal.get("risk_reward_ratio", 2.0)
        buffer_mult = proposal.get("sl_buffer_atr_multiple", 1.2)

        decision = ai_result.get("action_decision", "REJECT")
        confidence = int(ai_result.get("confidence_score", 0.0) * 100)
        assessment = ai_result.get("risk_assessment", {})
        primary_threat = assessment.get("primary_threat", "N/A")
        counter_args = assessment.get("counter_arguments", [])
        recommendation = ai_result.get("trade_recommendation", {})
        instruction = recommendation.get("instruction", "N/A")

        status_emoji = "🛡️ <b>PHÊ DUYỆT (APPROVE)</b>" if decision == "APPROVE" else "⛔ <b>TỪ CHỐI (REJECT)</b>"
        action_emoji = "🟢 LONG / BUY" if "BUY" in action else "🔴 SHORT / SELL"

        msg = (
            f"🤖 <b>AI TRADING COPILOT SIGNAL #{signal_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Cặp Giao Dịch:</b> <code>{symbol}</code> (Khung 15m)\n"
            f"🎯 <b>Hành Động:</b> {action_emoji} (<code>{action}</code>)\n"
            f"⚖️ <b>Phán Quyết AI:</b> {status_emoji} (Độ tin cậy: {confidence}%)\n\n"
            f"📊 <b>THÔNG SỐ TOÁN HỌC XÁC ĐỊNH (RISK ENGINE):</b>\n"
            f"• <b>Entry:</b> <code>${entry:,.2f}</code>\n"
            f"• <b>Stop Loss:</b> <code>${sl:,.2f}</code> (Đệm ATR: {buffer_mult}x)\n"
            f"• <b>Take Profit (1:2.0):</b> <code>${tp:,.2f}</code>\n"
            f"• <b>Khối Lượng Coin:</b> <code>{size}</code>\n"
            f"• <b>Mức Rủi Ro Cố Định:</b> <code>${risk_usd:.2f} USD (1.0%)</code>\n"
            f"• <b>Tỷ Lệ R:R:</b> <code>1:{rr}</code>\n\n"
            f"🛡️ <b>PHẢN BIỆN RỦI RO (DEVIL'S ADVOCATE):</b>\n"
            f"⚠️ <i>Mối đe dọa chính:</i> {primary_threat}\n"
        )

        if counter_args:
            msg += "🔍 <i>Lý do phản biện:</i>\n"
            for arg in counter_args:
                msg += f"  - {arg}\n"

        msg += (
            f"\n💡 <b>HƯỚNG DẪN HÀNH ĐỘNG:</b>\n"
            f"👉 {instruction}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        return msg

    def send_telegram_alert(
        self,
        signal_id: int,
        symbol: str,
        proposal: Dict[str, Any],
        ai_result: Dict[str, Any]
    ) -> bool:
        """Gửi tin nhắn Telegram kèm các phím bấm tương tác Inline Keyboard"""
        if not self.telegram_enabled:
            return False

        text = self.format_telegram_message(signal_id, symbol, proposal, ai_result)
        decision = ai_result.get("action_decision", "REJECT")

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Khớp lệnh Paper", "callback_data": f"paper_exec_{signal_id}"},
                    {"text": "❌ Bỏ qua", "callback_data": f"ignore_{signal_id}"}
                ]
            ]
        } if decision == "APPROVE" else {
            "inline_keyboard": [
                [
                    {"text": "ℹ️ Đã ghi nhận từ chối", "callback_data": f"ack_{signal_id}"}
                ]
            ]
        }

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": reply_markup
        }

        try:
            resp = requests.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                logger.info(f"Đã gửi cảnh báo Signal #{signal_id} tới Telegram thành công.")
                return True
            else:
                logger.warning(f"Gửi Telegram thất bại (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Lỗi kết nối Telegram Bot: {e}")
        return False

    def print_terminal_card(
        self,
        signal_id: int,
        symbol: str,
        proposal: Dict[str, Any],
        ai_result: Dict[str, Any]
    ):
        """In thẻ tín hiệu trực quan, chuyên nghiệp lên màn hình Console"""
        decision = ai_result.get("action_decision", "REJECT")
        action = proposal.get("action", "BUY_LIMIT")
        entry = proposal.get("entry_price", 0)
        sl = proposal.get("stop_loss", 0)
        tp = proposal.get("take_profit", 0)
        size = proposal.get("position_size", 0)
        risk_usd = proposal.get("risk_amount_usd", 2.0)
        rr = proposal.get("risk_reward_ratio", 2.0)
        sl_buffer = proposal.get("sl_buffer_atr_multiple", 1.2)
        confidence = int(ai_result.get("confidence_score", 0.0) * 100)

        assessment = ai_result.get("risk_assessment", {})
        primary_threat = assessment.get("primary_threat", "N/A")
        counter_args = assessment.get("counter_arguments", [])
        recommendation = ai_result.get("trade_recommendation", {})
        instruction = recommendation.get("instruction", "N/A")

        # Color codes
        c_cyan = Fore.CYAN if self.enable_color else ""
        c_white = Fore.WHITE if self.enable_color else ""
        c_reset = Style.RESET_ALL if self.enable_color else ""
        c_yellow = Fore.YELLOW if self.enable_color else ""

        if decision == "APPROVE":
            c_dec = Fore.GREEN if self.enable_color else ""
            status_text = "[ APPROVE - ĐƯỢC PHÉP VÀO LỆNH ]"
        elif decision == "WAIT":
            c_dec = Fore.YELLOW if self.enable_color else ""
            status_text = "[ WAIT - CHỜ NẾN XÁC NHẬN ]"
        else:
            c_dec = Fore.RED if self.enable_color else ""
            status_text = "[ REJECT - TỪ CHỐI BẢO TOÀN VỐN ]"

        width = 72
        line_horiz = "=" * width
        line_thin = "-" * width

        print()
        print(f"{c_cyan}{line_horiz}{c_reset}")
        print(f"{c_cyan}|{c_reset} {Style.BRIGHT}{c_white}AI TRADING COPILOT | SIGNAL #{signal_id} | {symbol} (15m){c_reset}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}{line_thin}{c_reset}")
        print(f"{c_cyan}|{c_reset} QUYẾT ĐỊNH CỦA AI : {c_dec}{Style.BRIGHT}{status_text}{c_reset} (Độ tin cậy: {confidence}%)".ljust(width + 12) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset} HÀNH ĐỘNG ĐỀ XUẤT : {action}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}{line_thin}{c_reset}")
        print(f"{c_cyan}|{c_reset} {Style.BRIGHT}[ TẦNG TOÁN HỌC XÁC ĐỊNH - RISK ENGINE ]{c_reset}".ljust(width + 8) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  • Entry Price       : ${entry:,.2f}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  • Stop Loss         : ${sl:,.2f}  (Đệm an toàn: {sl_buffer}x ATR)".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  • Take Profit (1:2) : ${tp:,.2f}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  • Position Size     : {size} {symbol.split('/')[0]}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  • Fixed Risk Amount : ${risk_usd:.2f} USD (Cố định 1% vốn)".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  • Risk/Reward Ratio : 1:{rr}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}{line_thin}{c_reset}")
        print(f"{c_cyan}|{c_reset} {Style.BRIGHT}[ TẦNG PHẢN BIỆN RỦI RO - DEVIL'S ADVOCATE ]{c_reset}".ljust(width + 8) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}|{c_reset}  {c_yellow}Mối đe dọa chính:{c_reset} {primary_threat}".ljust(width + 8) + f"{c_cyan}|{c_reset}")
        for i, arg in enumerate(counter_args, 1):
            print(f"{c_cyan}|{c_reset}   {i}. {arg}".ljust(width - 1) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}{line_thin}{c_reset}")
        print(f"{c_cyan}|{c_reset} {Style.BRIGHT}HƯỚNG DẪN:{c_reset} {instruction}".ljust(width + 8) + f"{c_cyan}|{c_reset}")
        print(f"{c_cyan}{line_horiz}{c_reset}")
        print()
