"""
main_daemon.py
Hệ Thống AI Trading Copilot & Deterministic Risk Management Engine
File chạy chính (Event Loop / Scanner Daemon / CLI Interface)
Tác giả: Hoàng Xuân Bách - v1.0.0-PROD-SPEC
"""

import sys
import os
import time
import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import yaml

# Đảm bảo đường dẫn import tương đối từ thư mục gốc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Đảm bảo Windows Console hiển thị UTF-8 tiếng Việt và ký tự đặc biệt
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.data_feed import MarketDataFeed
from core.indicator_engine import QuantitativeIndicatorEngine
from core.risk_engine import DeterministicRiskEngine, PositionProposal
from core.copilot_agent import AICopilotAgent
from storage.database import DatabaseManager
from guardrails.risk_guardrails import RiskGuardrails
from alerts.telegram_bot import AlertDispatcher
from execution.order_executor import OrderExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("TradingCopilot")


class TradingCopilotSystem:
    """
    Hệ Thống AI Trading Copilot Tổng Thể:
    Điều phối luồng dữ liệu 1 chiều qua 5 Phân Tầng:
    DataFeed -> IndicatorEngine -> RiskEngine -> CopilotAgent -> AlertDispatcher & Storage
    """
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)

        # 1. Khởi tạo Storage Database
        db_path = self.config.get("storage", {}).get("database_path", "storage/trades.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = DatabaseManager(db_path=db_path)

        # Đọc vốn và tỷ lệ rủi ro từ Database nếu có
        saved_equity = self.db.get_account_equity(default=self.config.get("account", {}).get("equity_usd", 200.0))
        saved_risk_pct = self.db.get_risk_percent(default=self.config.get("account", {}).get("fixed_risk_percent", 1.0))
        daily_loss_limit = round(saved_equity * 0.02, 2)

        # 2. Khởi tạo Guardrails
        g_cfg = self.config.get("guardrails", {})
        self.guardrails = RiskGuardrails(
            db=self.db,
            daily_loss_limit_usd=daily_loss_limit,
            max_open_positions=self.config.get("account", {}).get("max_open_positions", 2),
            breakeven_trigger_r=g_cfg.get("breakeven_trigger_r", 1.0),
            anti_tilt_consecutive_losses=g_cfg.get("anti_tilt_consecutive_losses", 2),
            cooldown_minutes=g_cfg.get("cooldown_minutes", 60)
        )

        # 3. Khởi tạo Tier 1: Data Feed
        symbols = self.config.get("strategy", {}).get("symbols", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        ring_buffer_size = self.config.get("strategy", {}).get("ring_buffer_size", 300)
        self.data_feed = MarketDataFeed(symbols=symbols, ring_buffer_size=ring_buffer_size, use_futures=True)

        # 4. Khởi tạo Tier 3: Deterministic Risk Engine
        acc_cfg = self.config.get("account", {})
        risk_cfg = self.config.get("risk_math", {})
        self.risk_engine = DeterministicRiskEngine(
            account_equity=saved_equity,
            risk_percent=saved_risk_pct,
            sl_buffer_mult=risk_cfg.get("sl_buffer_atr_mult", 1.2),
            forced_min_sl_mult=risk_cfg.get("forced_sl_atr_mult", 1.5),
            min_rr=risk_cfg.get("min_risk_reward", 2.0)
        )

        # 5. Khởi tạo Tier 4: Cognitive AI Copilot Agent
        llm_cfg = self.config.get("llm", {})
        self.copilot_agent = AICopilotAgent(
            provider=llm_cfg.get("provider", "ollama"),
            ollama_url=llm_cfg.get("ollama", {}).get("base_url", "http://localhost:11434/api/generate"),
            model_name=llm_cfg.get("ollama", {}).get("model", "qwen2.5-coder:7b"),
            openrouter_api_key=llm_cfg.get("openrouter", {}).get("api_key", ""),
            openrouter_model=llm_cfg.get("openrouter", {}).get("model", "deepseek/deepseek-r1"),
            timeout_seconds=llm_cfg.get("ollama", {}).get("timeout_seconds", 5.0),
            enable_fallback=llm_cfg.get("deterministic_fallback_enabled", True)
        )

        # 6. Khởi tạo Tier 5: Alert Dispatcher
        alert_cfg = self.config.get("alerts", {})
        tg_cfg = alert_cfg.get("telegram", {})
        self.dispatcher = AlertDispatcher(
            telegram_enabled=tg_cfg.get("enabled", False),
            bot_token=tg_cfg.get("bot_token", ""),
            chat_id=tg_cfg.get("chat_id", ""),
            enable_color=alert_cfg.get("cli_color", True)
        )

        # 7. Khởi tạo Order Executor (Tự động đặt lệnh sàn khi AI APPROVE)
        self.order_executor = OrderExecutor(db=self.db)

    def _load_config(self, path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Không tìm thấy file cấu hình tại {path}")
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        # Tự động nạp biến môi trường cho Render / Cloud Deployment
        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            cfg.setdefault("alerts", {}).setdefault("telegram", {})["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
            cfg["alerts"]["telegram"]["enabled"] = True
        if os.environ.get("TELEGRAM_CHAT_ID"):
            cfg.setdefault("alerts", {}).setdefault("telegram", {})["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
        if os.environ.get("OPENROUTER_API_KEY"):
            cfg.setdefault("llm", {}).setdefault("openrouter", {})["api_key"] = os.environ["OPENROUTER_API_KEY"]
            cfg.setdefault("llm", {})["provider"] = "openrouter"
        if os.environ.get("ACCOUNT_EQUITY"):
            cfg.setdefault("account", {})["equity_usd"] = float(os.environ["ACCOUNT_EQUITY"])

        return cfg

    def build_system_input_payload(
        self,
        symbol: str,
        quant_signals: Dict[str, Any],
        proposal: PositionProposal
    ) -> Dict[str, Any]:
        """
        Chuẩn hóa dữ liệu thành System Input Payload theo đúng chuẩn JSON Schema 4.1.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        current_price = quant_signals.get("current_price", proposal.entry_price)

        payload = {
            "timestamp": now_iso,
            "symbol": symbol,
            "timeframe": "15m",
            "market_data": {
                "current_price": current_price,
                "high_24h": quant_signals.get("high_24h", current_price),
                "low_24h": quant_signals.get("low_24h", current_price),
                "volume_trend": quant_signals.get("volume_trend", "NORMAL")
            },
            "quantitative_signals": {
                "trendline_status": quant_signals.get("trendline_status", "NEUTRAL"),
                "rsi_10": quant_signals.get("rsi_10", 50.0),
                "rsi_14": quant_signals.get("rsi_14", 50.0),
                "rsi_30": quant_signals.get("rsi_30", 50.0),
                "atr_14": quant_signals.get("atr_14", 100.0),
                "nearest_support": quant_signals.get("nearest_support", 0),
                "nearest_resistance": quant_signals.get("nearest_resistance", 0),
                "is_extreme_oversold": quant_signals.get("is_extreme_oversold", False),
                "is_extreme_overbought": quant_signals.get("is_extreme_overbought", False),
                "is_below_ema200_1h": quant_signals.get("is_below_ema200_1h", False),
                "ema200_1h_sloping_down": quant_signals.get("ema200_1h_sloping_down", False),
                "candle_patterns": quant_signals.get("candle_patterns", {}),
                "fvg": quant_signals.get("fvg", {})
            },
            "deterministic_math_proposal": {
                "proposed_action": proposal.action,
                "calculated_entry": proposal.entry_price,
                "calculated_sl": proposal.stop_loss,
                "sl_buffer_atr_multiple": proposal.sl_buffer_atr_multiple,
                "calculated_tp": proposal.take_profit,
                "risk_reward_ratio": f"1:{proposal.risk_reward_ratio}",
                "account_equity": proposal.account_equity,
                "fixed_risk_usd": proposal.risk_amount_usd,
                "calculated_position_size": proposal.position_size
            },
            "portfolio_state": {
                "active_positions_count": self.db.get_active_positions_count(),
                "correlated_exposure": "MEDIUM" if self.db.get_active_positions_count() == 1 else ("HIGH" if self.db.get_active_positions_count() >= 2 else "LOW"),
                "daily_realized_pnl": round(self.db.get_daily_realized_pnl(), 2),
                "news_blackout_active": False
            }
        }
        return payload

    def analyze_symbol(self, symbol: str) -> Optional[int]:
        """
        Quy trình xử lý khép kín cho 1 cặp giao dịch:
        1. Lấy dữ liệu nến 15m và 1h
        2. Tính toán chỉ báo định lượng
        3. Tính toán vị thế toán học (Position Proposal)
        4. Kiểm tra Guardrails
        5. Phản biện AI Copilot (Devil's Advocate)
        6. Lưu trữ và Gửi thông báo
        """
        df_15m = self.data_feed.get_dataframe(symbol, "15m")
        df_1h = self.data_feed.get_dataframe(symbol, "1h")

        if len(df_15m) < 35:
            logger.warning(f"Dữ liệu {symbol} chưa đủ 35 nến 15m. Bỏ qua lượt quét này.")
            return None

        # 1. TÍNH TOÁN CHỈ BÁO ĐỊNH LƯỢNG (Tier 2)
        try:
            quant = QuantitativeIndicatorEngine.compute_all_indicators(df_15m, df_1h)
        except Exception as e:
            logger.error(f"Lỗi tính chỉ báo cho {symbol}: {e}")
            return None

        current_price = quant["current_price"]
        atr_15m = quant["atr_14"]
        swing_low = quant["swing_low_5"]
        swing_high = quant["swing_high_5"]

        # 2. XÁC ĐỊNH HƯỚNG VÀ TÍNH TOÁN TOÁN HỌC (Tier 3)
        # Giả định thiết lập vào lệnh: Mua quanh hỗ trợ / Limit pullback hoặc Bán quanh kháng cự
        # Ưu tiên tìm cơ hội Long khi có tín hiệu hỗ trợ hoặc quá bán
        proposal = None
        if quant.get("is_extreme_oversold") or quant.get("trendline_status") == "BULLISH_BREAKOUT" or quant.get("candle_patterns", {}).get("is_pinbar_bullish"):
            entry_target = current_price
            proposal = self.risk_engine.calculate_long_proposal(symbol, entry_target, swing_low, atr_15m)
        elif quant.get("is_extreme_overbought") or quant.get("trendline_status") == "BEARISH_BREAKOUT":
            entry_target = current_price
            proposal = self.risk_engine.calculate_short_proposal(symbol, entry_target, swing_high, atr_15m)
        else:
            # Mặc định thử nghiệm proposal Long tại vùng hỗ trợ an toàn
            entry_target = current_price
            proposal = self.risk_engine.calculate_long_proposal(symbol, entry_target, swing_low, atr_15m)

        if not proposal or not proposal.is_valid:
            logger.debug(f"{symbol}: Không tạo được proposal hợp lệ. Lý do: {proposal.rejection_reason if proposal else 'None'}")
            return None

        # 3. ĐÓNG GÓI JSON PAYLOAD CHO AI (Tier 4)
        payload = self.build_system_input_payload(symbol, quant, proposal)

        # 4. TRUYỀN DỮ LIỆU SANG TẦNG SUY LUẬN AI (DEVIL'S ADVOCATE)
        ai_result = self.copilot_agent.evaluate_setup(payload)

        # 5. LƯU VÀO DATABASE (Tier 5 Storage)
        ai_decision = ai_result.get("action_decision", "REJECT")
        ai_confidence = float(ai_result.get("confidence_score", 0.0))
        ai_reasoning = (
            f"Threat: {ai_result.get('risk_assessment', {}).get('primary_threat', '')} | "
            f"Counters: {'; '.join(ai_result.get('risk_assessment', {}).get('counter_arguments', []))}"
        )

        signal_id = self.db.record_signal(
            symbol=symbol,
            timeframe="15m",
            entry_price=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            position_size=proposal.position_size,
            risk_amount_usd=proposal.risk_amount_usd,
            risk_reward_ratio=proposal.risk_reward_ratio,
            ai_decision=ai_decision,
            ai_confidence=ai_confidence,
            ai_reasoning=ai_reasoning,
            execution_status="PROPOSED"
        )

        # 6. PHÁT TÍN HIỆU CẢNH BÁO (Tier 5 Dispatcher)
        proposal_dict = proposal.to_dict()
        self.dispatcher.print_terminal_card(signal_id, symbol, proposal_dict, ai_result)
        self.dispatcher.send_telegram_alert(signal_id, symbol, proposal_dict, ai_result)

        # 7. TỰ ĐỘNG ĐẶT LỆNH SÀN (AUTO-TRADE) KHI AI COPILOT APPROVE
        if ai_decision == "APPROVE":
            if self.db.is_auto_trade_enabled():
                logger.info(f"⚡ [AUTO-TRADE]: AI APPROVE cho {symbol}! Tiến hành gửi lệnh lên sàn...")
                exec_res = self.order_executor.execute_signal(symbol, proposal_dict, ai_result, signal_id)
                self.dispatcher.send_auto_trade_alert(symbol, proposal_dict, exec_res)
                if exec_res.get("executed"):
                    print(f"✅ [AUTO-TRADE EXECUTED]: Đã đặt lệnh {proposal.action} {symbol} thành công trên sàn {exec_res.get('exchange', '').upper()} (Order #{exec_res.get('order_id')})!")
                else:
                    print(f"⚠️ [AUTO-TRADE FAILED]: Đặt lệnh {symbol} thất bại: {exec_res.get('message')}")
            else:
                logger.info(f"ℹ️ [AUTO-TRADE]: AI phê duyệt APPROVE cho {symbol} nhưng Auto-Trade đang TẮT.")

        return signal_id

    def run_scanner_cycle(self):
        """Chạy một chu kỳ quét tất cả các cặp trong watchlist"""
        # Lắng nghe và xử lý lệnh điều khiển Telegram Bot (/autotrade on/off, /setkeys, /testkeys)
        self.dispatcher.poll_telegram_updates(self.db, self.order_executor)

        # 0. Đồng bộ cấu hình vốn & tỷ lệ rủi ro từ Database nếu người dùng đã cập nhật
        current_equity = self.db.get_account_equity(default=self.risk_engine.account_equity)
        current_risk_pct = self.db.get_risk_percent(default=self.risk_engine.risk_percent)
        if current_equity != self.risk_engine.account_equity or current_risk_pct != self.risk_engine.risk_percent:
            self.risk_engine.update_account_equity(current_equity, current_risk_pct)
            new_daily_limit = round(current_equity * 0.02, 2)
            self.guardrails.update_daily_loss_limit(new_daily_limit)
            logger.info(f"Đã đồng bộ vốn mới: ${current_equity:,.2f} USD | Rủi ro: {current_risk_pct}% (${self.risk_engine.max_risk_usd:.2f}) | Ngưỡng ngắt mạch: ${new_daily_limit:.2f}")

        symbols = self.config.get("strategy", {}).get("symbols", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

        # Kiểm tra Guardrails trước khi quét
        can_trade, block_reason = self.guardrails.check_can_scan_and_propose()
        if not can_trade:
            logger.warning(f"GUARDRAIL CHẶN QUÉT: {block_reason}")
            return

        logger.info(f"Bắt đầu đồng bộ nến từ sàn Binance cho {len(symbols)} cặp...")
        self.data_feed.sync_buffers(symbols=symbols, timeframes=["15m", "1h"])

        # Rà soát Breakeven cho các vị thế đang mở
        current_prices = {s: self.data_feed.get_current_price(s) for s in symbols}
        valid_prices = {k: v for k, v in current_prices.items() if v is not None}
        if valid_prices:
            be_updates = self.guardrails.check_and_update_breakeven(valid_prices)
            if be_updates:
                for u in be_updates:
                    print(f"⚡ [BREAKEVEN AUTO-TRIGGER]: Đã đôn SL về Entry cho {u['symbol']} {u['side']} tại ${u['entry']:,.2f}!")

        # Quét và phân tích từng cặp
        for sym in symbols:
            try:
                self.analyze_symbol(sym)
            except Exception as e:
                logger.error(f"Lỗi phân tích {sym}: {e}", exc_info=True)

    def run_daemon(self, interval_seconds: int = 60):
        """Vận hành ở chế độ Daemon quét nền liên tục"""
        logger.info("=== HỆ THỐNG AI TRADING COPILOT DAEMON ĐÃ KHỞI ĐỘNG ===")
        logger.info(f"Chu kỳ quét: {interval_seconds} giây. Nhấn Ctrl+C để dừng.")
        try:
            while True:
                self.run_scanner_cycle()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("Người dùng yêu cầu dừng hệ thống. Đang tắt an toàn...")

    def show_status(self):
        """Hiển thị trạng thái tài khoản, vị thế mở và bảo vệ guardrails"""
        report = self.guardrails.get_guardrails_status_report()
        stats = self.db.get_journal_stats()
        positions = self.db.get_active_positions()

        curr_eq = self.db.get_account_equity(default=self.risk_engine.account_equity)
        curr_risk = self.db.get_risk_percent(default=self.risk_engine.risk_percent)
        risk_usd = round(curr_eq * (curr_risk / 100.0), 2)

        cfg = self.db.get_exchange_config()
        is_auto = self.db.is_auto_trade_enabled()
        env_str = "Testnet (Demo)" if cfg.get("is_testnet") else "MAINNET REAL"
        masked_key = (cfg.get("api_key")[:6] + "...") if len(cfg.get("api_key", "")) > 6 else "(Chưa điền)"

        print("\n" + "=" * 65)
        print("📊 BÁO CÁO TRẠNG THÁI HỆ THỐNG (SYSTEM HEALTH & GUARDRAILS)")
        print("=" * 65)
        print(f"• Vốn khả dụng thiết lập   : ${curr_eq:,.2f} USD (Rủi ro: {curr_risk}% = ${risk_usd:,.2f}/lệnh)")
        print(f"• Tự động đặt lệnh (Auto)  : {'[ BẬT - SẴN SÀNG ]' if is_auto else '[ TẮT ]'} | Sàn: {cfg.get('exchange', 'binance').upper()} ({env_str})")
        print(f"• API Key sàn cấu hình     : {masked_key}")
        print(f"• Lãi/Lỗ trong ngày (UTC) : ${report['daily_pnl_usd']:,.2f} USD (Giới hạn: -${report['daily_loss_limit_usd']:.2f})")
        print(f"• Daily Circuit Breaker    : {'[ KÍCH HOẠT KHÓA ]' if report['daily_circuit_breaker_active'] else '[ AN TOÀN ]'}")
        print(f"• Số vị thế đang mở        : {report['active_positions_count']}/{report['max_open_positions_allowed']}")
        print(f"• Lệnh SL liên tiếp        : {report['consecutive_losses_count']}")
        print(f"• Anti-Tilt Cooldown       : {'[ ĐANG LÀM NGUỘI ]' if report['anti_tilt_cooldown_active'] else '[ SẴN SÀNG ]'}")
        print(f"• Quyền vào lệnh hiện tại  : {'✅ ĐƯỢC PHÉP' if report['can_trade'] else '❌ ĐANG BỊ KHÓA'}")
        print("-" * 65)
        print("📈 THỐNG KÊ TRADING JOURNAL:")
        print(f"• Tổng số lệnh đã đóng     : {stats['total_trades']}")
        print(f"• Tỷ lệ thắng (Winrate)    : {stats['winrate_percent']}% ({stats['wins']} Thắng / {stats['losses']} Thua)")
        print(f"• Profit Factor            : {stats['profit_factor']}")
        print(f"• Lợi nhuận ròng (Net PnL) : ${stats['net_pnl_usd']:,.2f} USD")
        print("-" * 65)
        if positions:
            print(f"📍 DANH SÁCH {len(positions)} VỊ THẾ ĐANG MỞ:")
            for p in positions:
                be_tag = " [HÒA VỐN]" if p["is_breakeven"] else ""
                print(f"  - #{p['id']} {p['symbol']} {p['side']} | Entry: ${p['entry_price']:,.2f} | SL: ${p['current_sl']:,.2f}{be_tag} | Size: {p['position_size']}")
        else:
            print("📍 Không có vị thế nào đang mở.")
        print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="AI Trading Copilot & Deterministic Risk Management Engine")
    parser.add_argument("mode", choices=["daemon", "scan", "status", "simulate", "web"], default="scan", nargs="?",
                        help="Chế độ chạy: scan (quét 1 lần), daemon (chạy nền), status (kiểm tra tài khoản), simulate (mô phỏng), web (mở Dashboard)")
    parser.add_argument("--interval", type=int, default=60, help="Chu kỳ quét nền tính bằng giây (mặc định: 60s)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)), help="Cổng mạng cho Web Dashboard (mặc định: $PORT hoặc 8000)")
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "0.0.0.0"), help="Host IP lắng nghe (mặc định: 0.0.0.0)")
    parser.add_argument("--with-scanner", dest="with_scanner", action="store_true", default=None, help="Chạy luồng quét thị trường song song với Web Dashboard")
    parser.add_argument("--config", type=str, default="config/settings.yaml", help="Đường dẫn file settings.yaml")
    args = parser.parse_args()

    copilot = TradingCopilotSystem(config_path=args.config)

    if args.mode == "scan":
        print("Đang thực hiện quét 1 chu kỳ trên Binance...")
        copilot.run_scanner_cycle()
    elif args.mode == "daemon":
        copilot.run_daemon(interval_seconds=args.interval)
    elif args.mode == "status":
        copilot.show_status()
    elif args.mode == "simulate":
        print("Chạy kịch bản mô phỏng kiểm tra Devil's Advocate...")
        import test_system
        test_system.run_all_tests()
    elif args.mode == "web":
        from web.dashboard import run_dashboard_server
        db_path = copilot.config.get("storage", {}).get("database_path", "storage/trades.db")
        run_dashboard_server(host=args.host, port=args.port, db_path=db_path, with_scanner=args.with_scanner)


if __name__ == "__main__":
    main()
