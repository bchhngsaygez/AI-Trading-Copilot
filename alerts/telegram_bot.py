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
        self.last_update_id = 0

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

    def send_message(self, text: str, reply_markup: Optional[Dict] = None) -> bool:
        """Gửi tin nhắn tùy biến tới Telegram"""
        if not self.telegram_enabled:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            resp = requests.post(url, json=payload, timeout=5.0)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Lỗi gửi tin nhắn Telegram: {e}")
            return False

    def send_auto_trade_alert(
        self,
        symbol: str,
        proposal: Dict[str, Any],
        exec_res: Dict[str, Any]
    ) -> bool:
        """Bắn thông báo kết quả tự động khớp lệnh sàn giao dịch"""
        if not self.telegram_enabled:
            return False

        success = exec_res.get("executed", False)
        exchange = exec_res.get("exchange", "binance").upper()
        env_tag = "TESTNET" if exec_res.get("is_testnet", True) else "MAINNET REAL"
        order_id = exec_res.get("order_id", "N/A")
        action = proposal.get("action", "BUY_LIMIT")
        entry = proposal.get("entry_price", 0)
        sl = proposal.get("stop_loss", 0)
        tp = proposal.get("take_profit", 0)
        size = proposal.get("position_size", 0)
        sl_oid = exec_res.get("sl_order_id", "N/A")
        tp_oid = exec_res.get("tp_order_id", "N/A")

        if success:
            msg = (
                f"⚡ <b>[AUTO-TRADE ĐÃ ĐẶT LỆNH THÀNH CÔNG]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏛️ <b>Sàn Giao Dịch:</b> <code>{exchange}</code> (Chế độ: <b>{env_tag}</b>)\n"
                f"📌 <b>Cặp Coin:</b> <code>{symbol}</code>\n"
                f"🎯 <b>Loại Lệnh:</b> <code>{action}</code>\n"
                f"💰 <b>Giá Entry:</b> <code>${entry:,.2f}</code>\n"
                f"📦 <b>Khối Lượng:</b> <code>{size} {symbol.split('/')[0]}</code>\n"
                f"🛑 <b>Stop Loss:</b> <code>${sl:,.2f}</code> (Order #{sl_oid})\n"
                f"🎯 <b>Take Profit:</b> <code>${tp:,.2f}</code> (Order #{tp_oid})\n"
                f"🔢 <b>Mã Order Sàn:</b> <code>#{order_id}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Lệnh Limit và các rào chắn SL/TP đã được kích hoạt trực tiếp trên sàn!"
            )
        else:
            err = exec_res.get("raw", {}).get("error") or exec_res.get("message", "Lỗi không xác định")
            msg = (
                f"⚠️ <b>[AUTO-TRADE ĐẶT LỆNH THẤT BẠI]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏛️ <b>Sàn Giao Dịch:</b> <code>{exchange}</code> ({env_tag})\n"
                f"📌 <b>Cặp Coin:</b> <code>{symbol}</code> | <b>Hành Động:</b> {action}\n"
                f"❌ <b>Lý Do Lỗi:</b> <code>{err}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 Vui lòng kiểm tra lại số dư ký quỹ hoặc quyền hạn API Key của bạn."
            )

        return self.send_message(msg)

    def poll_telegram_updates(self, db, order_executor=None):
        """
        Lắng nghe và xử lý các lệnh điều khiển từ người dùng qua Telegram Bot:
        /autotrade on | /autotrade off | /autotrade status | /setkeys | /testkeys | /help
        """
        if not self.telegram_enabled:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 1}

        try:
            resp = requests.get(url, params=params, timeout=3.0)
            if resp.status_code != 200:
                return

            data = resp.json()
            updates = data.get("result", [])
            for upd in updates:
                self.last_update_id = max(self.last_update_id, upd.get("update_id", 0))
                msg = upd.get("message", {})
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))
                text = msg.get("text", "").strip()

                # Kiểm tra quyền: chỉ nhận lệnh từ chat_id đã cấu hình
                if str(chat_id) != str(self.chat_id) or not text:
                    continue

                self._handle_bot_command(text, db, order_executor)

        except Exception as e:
            logger.debug(f"Poll telegram updates error: {e}")

    def _handle_bot_command(self, text: str, db, order_executor):
        """Xử lý cú pháp lệnh bot"""
        cmd_parts = text.split()
        cmd = cmd_parts[0].lower()

        if cmd in ("/start", "/help"):
            help_msg = (
                f"🤖 <b>AI TRADING COPILOT | ĐIỀU KHIỂN TỰ ĐỘNG</b>\n\n"
                f"• <code>/autotrade on</code> - Bật tính năng tự động đặt lệnh khi AI APPROVE\n"
                f"• <code>/autotrade off</code> - Tắt tự động đặt lệnh (chỉ gửi cảnh báo)\n"
                f"• <code>/autotrade status</code> - Kiểm tra trạng thái kết nối & Auto-Trade\n"
                f"• <code>/testkeys</code> - Kiểm tra kết nối API Key và kiểm tra số dư ví sàn\n"
                f"• <code>/setkeys &lt;sàn&gt; &lt;key&gt; &lt;secret&gt; [testnet/real]</code> - Cài đặt API Key sàn\n"
                f"  <i>Ví dụ:</i> <code>/setkeys binance key123 sec456 testnet</code>\n"
                f"  <i>(Sàn hỗ trợ: binance, bybit)</i>\n"
                f"• <code>/status</code> - Xem trạng thái vốn, Daily Loss Breaker & Winrate"
            )
            self.send_message(help_msg)

        elif cmd == "/autotrade":
            sub = cmd_parts[1].lower() if len(cmd_parts) > 1 else "status"
            if sub == "on":
                db.set_auto_trade_enabled(True)
                cfg = db.get_exchange_config()
                env = "Testnet" if cfg.get("is_testnet") else "MAINNET REAL"
                self.send_message(
                    f"✅ <b>ĐÃ BẬT TỰ ĐỘNG ĐẶT LỆNH (AUTO-TRADE: ON)</b>\n"
                    f"🏛️ Sàn: <b>{cfg.get('exchange', 'binance').upper()}</b> ({env})\n"
                    f"🎯 Khi AI ra quyết định APPROVE, hệ thống sẽ tự động gửi lệnh Limit + SL/TP lên sàn."
                )
            elif sub == "off":
                db.set_auto_trade_enabled(False)
                self.send_message(
                    f"⏸️ <b>ĐÃ TẮT TỰ ĐỘNG ĐẶT LỆNH (AUTO-TRADE: OFF)</b>\n"
                    f"Hệ thống đã chuyển về chế độ chỉ báo và cảnh báo thủ công an toàn."
                )
            elif sub == "status":
                cfg = db.get_exchange_config()
                is_on = db.is_auto_trade_enabled()
                env = "Testnet" if cfg.get("is_testnet") else "MAINNET REAL"
                masked_key = (cfg.get("api_key")[:6] + "...") if len(cfg.get("api_key", "")) > 6 else "(Chưa có)"
                status_icon = "🟢 ĐANG BẬT" if is_on else "🔴 ĐANG TẮT"
                self.send_message(
                    f"⚙️ <b>TRẠNG THÁI TỰ ĐỘNG ĐẶT LỆNH</b>\n"
                    f"• Trạng Thái: <b>{status_icon}</b>\n"
                    f"• Sàn Giao Dịch: <code>{cfg.get('exchange', 'binance').upper()}</code>\n"
                    f"• Môi Trường: <b>{env}</b>\n"
                    f"• API Key: <code>{masked_key}</code>\n"
                    f"• Lệnh Gần Nhất: Xem trên Web Dashboard"
                )

        elif cmd == "/testkeys":
            cfg = db.get_exchange_config()
            if order_executor:
                client = order_executor.get_client_for_config(cfg)
                if not client:
                    self.send_message(f"❌ Chưa có API Key/Secret cho sàn {cfg.get('exchange', 'binance').upper()}. Dùng <code>/setkeys</code> để cài đặt.")
                    return
                res = client.test_connection()
                if res.get("success"):
                    self.send_message(f"✅ {res.get('message')}")
                else:
                    self.send_message(f"❌ {res.get('message')}")

        elif cmd == "/setkeys":
            if len(cmd_parts) < 4:
                self.send_message("❌ Sai cú pháp. Dùng:\n<code>/setkeys &lt;binance/bybit&gt; &lt;api_key&gt; &lt;api_secret&gt; [testnet/real]</code>")
                return
            exchange = cmd_parts[1].lower()
            api_key = cmd_parts[2]
            api_secret = cmd_parts[3]
            is_testnet = (cmd_parts[4].lower() != "real") if len(cmd_parts) > 4 else True
            db.save_exchange_config(
                exchange=exchange,
                api_key=api_key,
                api_secret=api_secret,
                is_testnet=is_testnet,
                auto_trade_enabled=db.is_auto_trade_enabled()
            )
            env_str = "TESTNET (Khuyên dùng)" if is_testnet else "MAINNET REAL"
            self.send_message(
                f"✅ <b>ĐÃ CẬP NHẬT API KEY THÀNH CÔNG!</b>\n"
                f"• Sàn: <b>{exchange.upper()}</b>\n"
                f"• Chế độ: <b>{env_str}</b>\n"
                f"💡 Hãy gõ <code>/testkeys</code> để kiểm tra số dư và quyền hạn ngay!\n"
                f"⚠️ <i>Mẹo bảo mật: Bạn có thể xóa tin nhắn vừa gửi chứa key trên Telegram.</i>"
            )

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
