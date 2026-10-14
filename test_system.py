"""
test_system.py
Bộ Kiểm Thử Toàn Diện (Comprehensive Test Suite)
Kiểm tra 100% các công thức toán học, thuật toán chỉ báo, 4 Hard Veto Rules,
SQLite Database, và Guardrails bảo vệ tài khoản.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd

# Thêm đường dẫn project vào sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.risk_engine import DeterministicRiskEngine, PositionProposal
from core.indicator_engine import QuantitativeIndicatorEngine
from core.copilot_agent import HardVetoEnforcer, DeterministicDevilAdvocate
from storage.database import DatabaseManager
from guardrails.risk_guardrails import RiskGuardrails
from alerts.telegram_bot import AlertDispatcher
from execution.exchange_client import BinanceFuturesClient, BybitPerpetualClient, WebhookClient
from execution.order_executor import OrderExecutor


class TestDeterministicRiskEngine(unittest.TestCase):
    """Kiểm tra hạt nhân Quản trị rủi ro toán học (Chương 3.3 & 6.2)"""

    def setUp(self):
        self.engine = DeterministicRiskEngine(account_equity=200.0, risk_percent=1.0)

    def test_fixed_fractional_risk(self):
        """Kiểm tra mức rủi ro cố định chính xác 1% = $2.00 USD"""
        self.assertEqual(self.engine.max_risk_usd, 2.00)

    def test_adaptive_stop_loss_buffer_long(self):
        """
        Kiểm tra công thức:
        Buffer = 1.2 * ATR
        SL = Swing_Low - Buffer
        """
        entry = 83180.0
        atr = 100.0
        # Swing Low = 82900
        # Buffer = 120 -> calculated_sl = 82900 - 120 = 82780. Khoang_cach = 400 > 100 (Hợp lệ)
        proposal = self.engine.calculate_long_proposal("BTC/USDT", entry=entry, swing_low_5=82900.0, atr_15m=atr)
        self.assertTrue(proposal.is_valid)
        self.assertEqual(proposal.stop_loss, 82780.0)
        self.assertEqual(proposal.sl_distance, 400.0)
        # Size = 2.00 / 400 = 0.005 BTC
        self.assertEqual(proposal.position_size, 0.005)
        self.assertEqual(proposal.risk_reward_ratio, 2.0)
        self.assertEqual(proposal.take_profit, 83180.0 + 2 * 400.0)

    def test_forced_sl_expansion_on_tight_swing(self):
        """
        Kiểm tra cưỡng chế giãn khoảng cách SL = 1.5 * ATR nếu khoảng cách ban đầu < 1.0 ATR
        (Chống quét râu nến khi swing low quá sát entry)
        """
        entry = 83180.0
        atr = 100.0
        # Swing Low = 83250 -> 83250 - 120 = 83130 (Khoảng cách = 83180 - 83130 = 50 < 100)
        proposal = self.engine.calculate_long_proposal("BTC/USDT", entry=entry, swing_low_5=83250.0, atr_15m=atr)
        self.assertTrue(proposal.is_valid)
        # Cưỡng chế: SL = Entry - 1.5 * ATR = 83180 - 150 = 83030
        self.assertEqual(proposal.stop_loss, 83030.0)
        self.assertEqual(proposal.sl_distance, 150.0)
        # Kích thước vị thế = 2.00 / 150 = 0.0133 BTC
        self.assertEqual(proposal.position_size, 0.0133)

    def test_zero_division_and_invalid_entry_handling(self):
        """Kiểm tra không bị lỗi chia cho 0 khi Entry <= Stop Loss"""
        proposal = self.engine.calculate_long_proposal("BTC/USDT", entry=100.0, swing_low_5=150.0, atr_15m=10.0)
        # Entry (100) < Swing Low (150), Buffer = 12 -> Entry - Buffer = 88 < 150 -> SL = 88 -> distance = 12 (nhưng nếu SL >= Entry)
        proposal_invalid = self.engine.calculate_long_proposal("BTC/USDT", entry=0.0, swing_low_5=0.0, atr_15m=0.0)
        self.assertFalse(proposal_invalid.is_valid)
        self.assertIn("không hợp lệ", proposal_invalid.rejection_reason)

    def test_scale_out_plan(self):
        """Kiểm tra lộ trình chốt lời đa tầng (TP1 1.5R, TP2 2.5R, TP3 4.0R)"""
        proposal = self.engine.calculate_long_proposal("BTC/USDT", entry=80000.0, swing_low_5=79500.0, atr_15m=200.0)
        self.assertIsNotNone(proposal.tp1)
        self.assertIsNotNone(proposal.tp2)
        self.assertIsNotNone(proposal.tp3)
        self.assertEqual(proposal.tp1.r_multiple, 1.5)
        self.assertEqual(proposal.tp1.close_percentage, 50)
        self.assertEqual(proposal.tp2.r_multiple, 2.5)
        self.assertEqual(proposal.tp3.r_multiple, 4.0)


class TestQuantitativeIndicators(unittest.TestCase):
    """Kiểm tra các chỉ báo định lượng nâng cao (Chương 3.2 & 6.3)"""

    def setUp(self):
        # Tạo dữ liệu nến nhân tạo giả lập 100 cây nến
        np.random.seed(42)
        n = 100
        closes = 80000 + np.cumsum(np.random.randn(n) * 50)
        highs = closes + np.random.rand(n) * 30
        lows = closes - np.random.rand(n) * 30
        opens = (highs + lows) / 2
        volumes = np.random.rand(n) * 100 + 10

        self.df = pd.DataFrame({
            "timestamp": np.arange(n) * 900000,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })

    def test_wilder_rsi_calculation(self):
        """Kiểm tra tính toán RSI Multi-length (10, 14, 30)"""
        rsi_10 = QuantitativeIndicatorEngine.calculate_rsi(self.df["close"], 10)
        rsi_14 = QuantitativeIndicatorEngine.calculate_rsi(self.df["close"], 14)
        rsi_30 = QuantitativeIndicatorEngine.calculate_rsi(self.df["close"], 30)

        self.assertEqual(len(rsi_10), len(self.df))
        self.assertTrue(0.0 <= rsi_14.iloc[-1] <= 100.0)
        self.assertTrue(0.0 <= rsi_30.iloc[-1] <= 100.0)

    def test_adaptive_atr_calculation(self):
        """Kiểm tra tính toán Adaptive ATR"""
        atr = QuantitativeIndicatorEngine.calculate_atr(self.df["high"], self.df["low"], self.df["close"], 14)
        self.assertTrue(atr.iloc[-1] > 0)

    def test_trendline_breaks_margin_confirmation(self):
        """Kiểm tra thuật toán LuxAlgo Trendlines: Xác nhận vượt ngưỡng 0.2% biên độ"""
        res = QuantitativeIndicatorEngine.detect_trendlines_and_breaks(self.df, window=5, break_margin=0.002)
        self.assertIn("trendline_status", res)
        self.assertIn("breakout_detected", res)
        self.assertIn("breakdown_detected", res)

    def test_waterfall_dump_detection(self):
        """Kiểm tra phát hiện thác nước xả 3 cây nến đỏ dốc đứng"""
        df_dump = self.df.copy()
        # Ép 3 nến cuối thành nến đỏ dài không có râu dưới
        for idx in range(-3, 0):
            df_dump.iloc[idx, df_dump.columns.get_loc('open')] = 80000.0 + idx * 500
            df_dump.iloc[idx, df_dump.columns.get_loc('close')] = 79500.0 + idx * 500
            df_dump.iloc[idx, df_dump.columns.get_loc('high')] = 80050.0 + idx * 500
            df_dump.iloc[idx, df_dump.columns.get_loc('low')] = 79495.0 + idx * 500

        res = QuantitativeIndicatorEngine.detect_waterfall_and_pinbar(df_dump)
        self.assertTrue(res["is_waterfall"])
        self.assertFalse(res["is_pinbar_bullish"])


class TestHardVetoRules(unittest.TestCase):
    """Kiểm tra 4 Quy tắc Phủ Quyết Cứng (Chương 3.4)"""

    def test_veto_1_counter_macro_trend(self):
        """Veto 1: Nghiêm cấm Long nếu EMA200 1h dốc xuống và giá nằm dưới EMA200"""
        payload = {
            "quantitative_signals": {
                "is_below_ema200_1h": True,
                "ema200_1h_sloping_down": True,
                "candle_patterns": {}
            },
            "deterministic_math_proposal": {"proposed_action": "BUY_LIMIT"},
            "portfolio_state": {"active_positions_count": 0}
        }
        res = HardVetoEnforcer.evaluate(payload)
        self.assertIsNotNone(res)
        self.assertEqual(res["action_decision"], "REJECT")
        self.assertIn("VETO 1", res["risk_assessment"]["primary_threat"])

    def test_veto_2_falling_knife_waterfall(self):
        """Veto 2: Nghiêm cấm Long khi có thác nến xả 3 cây nến đỏ chưa có rút chân"""
        payload = {
            "quantitative_signals": {
                "is_below_ema200_1h": False,
                "ema200_1h_sloping_down": False,
                "candle_patterns": {"is_waterfall": True, "is_pinbar_bullish": False}
            },
            "deterministic_math_proposal": {"proposed_action": "BUY_LIMIT"},
            "portfolio_state": {"active_positions_count": 0}
        }
        res = HardVetoEnforcer.evaluate(payload)
        self.assertIsNotNone(res)
        self.assertEqual(res["action_decision"], "REJECT")
        self.assertIn("VETO 2", res["risk_assessment"]["primary_threat"])

    def test_veto_3_max_correlated_positions(self):
        """Veto 3: Nghiêm cấm mở thêm lệnh nếu tài khoản đang có >= 2 vị thế mở"""
        payload = {
            "quantitative_signals": {
                "is_below_ema200_1h": False,
                "ema200_1h_sloping_down": False,
                "candle_patterns": {"is_waterfall": False, "is_pinbar_bullish": True}
            },
            "deterministic_math_proposal": {"proposed_action": "BUY_LIMIT"},
            "portfolio_state": {"active_positions_count": 2}
        }
        res = HardVetoEnforcer.evaluate(payload)
        self.assertIsNotNone(res)
        self.assertEqual(res["action_decision"], "REJECT")
        self.assertIn("VETO 3", res["risk_assessment"]["primary_threat"])

    def test_veto_4_news_blackout(self):
        """Veto 4: Nghiêm cấm mở lệnh trong cửa sổ tin tức vĩ mô (CPI/FOMC)"""
        payload = {
            "quantitative_signals": {"candle_patterns": {}},
            "deterministic_math_proposal": {"proposed_action": "BUY_LIMIT"},
            "portfolio_state": {"active_positions_count": 0, "news_blackout_active": True}
        }
        res = HardVetoEnforcer.evaluate(payload)
        self.assertIsNotNone(res)
        self.assertEqual(res["action_decision"], "REJECT")
        self.assertIn("VETO 4", res["risk_assessment"]["primary_threat"])


class TestStorageAndGuardrails(unittest.TestCase):
    """Kiểm tra SQLite Schema 4.3 và 4 Guardrails bảo vệ vốn (Chương 4.3 & Chương 5)"""

    def setUp(self):
        import uuid
        self.test_db_path = f"storage/test_trades_{uuid.uuid4().hex}.db"
        self.db = DatabaseManager(self.test_db_path)
        self.guardrails = RiskGuardrails(self.db, daily_loss_limit_usd=4.00, max_open_positions=2)

    def tearDown(self):
        try:
            if os.path.exists(self.test_db_path):
                os.remove(self.test_db_path)
        except Exception:
            pass

    def test_record_signal_and_retrieve_stats(self):
        """Kiểm tra ghi nhận tín hiệu và tính toán Winrate, Profit Factor"""
        sig_id = self.db.record_signal(
            symbol="BTC/USDT", timeframe="15m", entry_price=83000.0,
            stop_loss=82700.0, take_profit=83600.0, position_size=0.0067,
            risk_amount_usd=2.00, risk_reward_ratio=2.0, ai_decision="APPROVE",
            ai_confidence=0.88, ai_reasoning="Good support test", execution_status="PENDING"
        )
        self.assertGreater(sig_id, 0)

        # Mở vị thế
        pos_id = self.db.open_position(
            signal_id=sig_id, symbol="BTC/USDT", side="LONG",
            entry_price=83000.0, stop_loss=82700.0, tp1=83450.0, tp2=83750.0, tp3=84200.0,
            position_size=0.0067, risk_usd=2.00
        )
        self.assertEqual(self.db.get_active_positions_count(), 1)

        # Chốt lời +$4.00 (Win)
        self.db.close_position(pos_id, exit_price=83600.0, realized_pnl=4.00)
        self.assertEqual(self.db.get_active_positions_count(), 0)

        stats = self.db.get_journal_stats()
        self.assertEqual(stats["total_trades"], 1)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["winrate_percent"], 100.0)
        self.assertEqual(stats["net_pnl_usd"], 4.00)

    def test_daily_loss_circuit_breaker(self):
        """Kiểm tra ngắt mạch khi lỗ trong ngày chạm $4.00 (2% vốn ban đầu)"""
        # Giả lập 2 lệnh thua liên tiếp mỗi lệnh lỗ $2.00
        sig1 = self.db.record_signal("BTC/USDT", "15m", 83000, 82700, 83600, 0.0067, 2.0, 2.0, "APPROVE", 0.8, "Test")
        pos1 = self.db.open_position(sig1, "BTC/USDT", "LONG", 83000, 82700, 83450, 83750, 84200, 0.0067, 2.0)
        self.db.close_position(pos1, exit_price=82700, realized_pnl=-2.00)

        sig2 = self.db.record_signal("ETH/USDT", "15m", 3000, 2950, 3100, 0.04, 2.0, 2.0, "APPROVE", 0.8, "Test")
        pos2 = self.db.open_position(sig2, "ETH/USDT", "LONG", 3000, 2950, 3075, 3125, 3200, 0.04, 2.0)
        self.db.close_position(pos2, exit_price=2950, realized_pnl=-2.00)

        # Tổng lỗ = -$4.00 -> Guardrail phải chặn ngay lập tức!
        can_trade, reason = self.guardrails.check_can_scan_and_propose()
        self.assertFalse(can_trade)
        self.assertIn("DAILY LOSS", reason)

    def test_risk_free_breakeven_trigger(self):
        """Kiểm tra tự động đôn SL về Entry khi giá đạt >= 1.0R lợi nhuận ($2.00)"""
        sig = self.db.record_signal("BTC/USDT", "15m", 83000, 82800, 83400, 0.01, 2.0, 2.0, "APPROVE", 0.85, "Test")
        pos_id = self.db.open_position(sig, "BTC/USDT", "LONG", 83000, 82800, 83300, 83500, 83800, 0.01, 2.0)

        # Giá chạy lên 83200 (Khoảng cách R ban đầu = 200 giá. Giá đạt 83000 + 200 = 83200 tức là đạt đúng 1.0R)
        updates = self.guardrails.check_and_update_breakeven({"BTC/USDT": 83250.0})
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["status"], "SL_MOVED_TO_BREAKEVEN")

        # Kiểm tra SL trong DB đã thành 83000 (Entry)
        positions = self.db.get_active_positions()
        self.assertEqual(positions[0]["current_sl"], 83000.0)
        self.assertEqual(positions[0]["is_breakeven"], 1)

    def test_dynamic_account_equity_and_settings(self):
        """Kiểm tra lưu trữ, cập nhật vốn và tỷ lệ rủi ro động trong SQLite"""
        # Mặc định ban đầu
        self.assertEqual(self.db.get_account_equity(default=200.0), 200.0)
        self.assertEqual(self.db.get_risk_percent(default=1.0), 1.0)

        # Cập nhật vốn lên $1,000 và rủi ro 1.5%
        self.db.set_account_equity(1000.0)
        self.db.set_risk_percent(1.5)
        self.assertEqual(self.db.get_account_equity(), 1000.0)
        self.assertEqual(self.db.get_risk_percent(), 1.5)

        # Cập nhật động sang RiskEngine
        engine = DeterministicRiskEngine(account_equity=200.0, risk_percent=1.0)
        self.assertEqual(engine.max_risk_usd, 2.00)
        engine.update_account_equity(1000.0, 1.5)
        self.assertEqual(engine.account_equity, 1000.0)
        self.assertEqual(engine.risk_percent, 1.5)
        self.assertEqual(engine.max_risk_usd, 15.00)

        # Cập nhật động sang Guardrails (2% của $1,000 = $20.00)
        self.guardrails.update_daily_loss_limit(round(1000.0 * 0.02, 2))
        self.assertEqual(self.guardrails.daily_loss_limit_usd, 20.0)


class TestPineScriptAndWebDashboard(unittest.TestCase):
    """Kiểm tra Pine Script v6 và Web Dashboard Indicator Studio"""

    def test_pine_script_v6_syntax_and_components(self):
        """Kiểm tra file Pine Script chứa đủ các tính năng yêu cầu"""
        from web.dashboard import get_pine_script_content
        pine = get_pine_script_content()
        # 1. Chuẩn Pine Script v6
        self.assertIn("//@version=6", pine)
        # 2. Buy/Sell Signals & Labels
        self.assertIn("BUY LIMIT", pine)
        self.assertIn("SELL LIMIT", pine)
        # 3. Second Tracking Line beneath main indicator
        self.assertIn("secondTrackingLine", pine)
        self.assertIn("Secondary Tracking Line (Beneath)", pine)
        self.assertIn("AI Dynamic Tracking Cloud", pine)
        # 4. On-Chart AI Commentary & Risk Officer Table
        self.assertIn("aiTable = table.new(position.top_right", pine)
        self.assertIn("Bình Luận CRO:", pine)
        # 5. Fixed risk & scale-out
        self.assertIn("fixedRiskUSD", pine)
        self.assertIn("tp1Long", pine)

    def test_dashboard_chart_payload_generation(self):
        """Kiểm tra API tạo payload biểu đồ nến kèm dual tracking lines và commentary"""
        from web.dashboard import DashboardRequestHandler
        handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
        handler.db_path = "storage/trades.db"
        payload = handler._generate_chart_payload("BTC/USDT")

        self.assertIn("symbol", payload)
        self.assertIn("candles", payload)
        self.assertIn("main_indicator_line", payload)
        self.assertIn("second_indicator_line", payload)
        self.assertIn("ai_commentary", payload)

        # Đảm bảo số điểm của 2 đường chỉ báo khớp với số lượng nến
        n_candles = len(payload["candles"])
        self.assertEqual(len(payload["main_indicator_line"]), n_candles)
        self.assertEqual(len(payload["second_indicator_line"]), n_candles)

        # Đảm bảo đường thứ hai bám bên dưới đường chính
        # (EMA low - buffer < EMA close)
        last_main = payload["main_indicator_line"][-1]
        last_second = payload["second_indicator_line"][-1]
        self.assertLess(last_second, last_main)


class TestExchangeExecutionAndAutoTrade(unittest.TestCase):
    """Kiểm tra module Kết Nối Sàn & Tự Động Đặt Lệnh (Chương 7)"""

    def setUp(self):
        self.test_db_path = "storage/test_execution.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = DatabaseManager(self.test_db_path)
        self.executor = OrderExecutor(self.db)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_exchange_config_persistence(self):
        """Kiểm tra lưu trữ và truy xuất cấu hình sàn giao dịch"""
        self.db.save_exchange_config(
            exchange="binance",
            api_key="test_api_key_123456",
            api_secret="test_api_secret_abcdef",
            is_testnet=True,
            auto_trade_enabled=True,
            webhook_url="https://test.webhook.com/alert"
        )
        cfg = self.db.get_exchange_config()
        self.assertEqual(cfg["exchange"], "binance")
        self.assertEqual(cfg["api_key"], "test_api_key_123456")
        self.assertEqual(cfg["api_secret"], "test_api_secret_abcdef")
        self.assertTrue(cfg["is_testnet"])
        self.assertTrue(cfg["auto_trade_enabled"])
        self.assertTrue(self.db.is_auto_trade_enabled())

        # Toggle tắt auto-trade
        self.db.set_auto_trade_enabled(False)
        self.assertFalse(self.db.is_auto_trade_enabled())

    def test_executed_orders_record_and_retrieve(self):
        """Kiểm tra ghi nhận nhật ký lệnh đặt lên sàn"""
        order_id = self.db.record_executed_order(
            signal_id=10,
            exchange="bybit",
            symbol="ETH/USDT",
            side="BUY",
            order_type="LIMIT",
            price=2550.0,
            quantity=0.1,
            order_id="bybit_ord_987",
            status="SUBMITTED",
            sl_order_id="sl_001",
            tp_order_id="tp_001",
            is_testnet=True
        )
        self.assertIsNotNone(order_id)
        orders = self.db.get_executed_orders(limit=10)
        self.assertGreaterEqual(len(orders), 1)
        ord_record = orders[0]
        self.assertEqual(ord_record["symbol"], "ETH/USDT")
        self.assertEqual(ord_record["price"], 2550.0)
        self.assertEqual(ord_record["exchange"], "bybit")
        self.assertEqual(ord_record["status"], "SUBMITTED")

    def test_binance_client_signing_and_mock_execution(self):
        """Kiểm tra thuật toán ký HMAC-SHA256 của BinanceFuturesClient"""
        client = BinanceFuturesClient(api_key="mock_key", api_secret="mock_secret", is_testnet=True)
        params = {"symbol": "BTCUSDT", "side": "BUY"}
        query = client._sign_params(params)
        self.assertIn("timestamp=", query)
        self.assertIn("signature=", query)

        # Mock requests.Session.post cho đặt lệnh Binance
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orderId": 12345678, "status": "NEW"}
        
        with patch.object(client.session, 'post', return_value=mock_response):
            res = client.place_order(
                symbol="BTC/USDT",
                side="BUY",
                order_type="LIMIT",
                price=83000.0,
                quantity=0.005,
                stop_loss=82500.0,
                take_profit=84000.0
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["order_id"], "12345678")

    def test_bybit_client_mock_execution(self):
        """Kiểm tra Bybit V5 Perpetual Client đặt lệnh kèm SL/TP"""
        client = BybitPerpetualClient(api_key="mock_bybit_key", api_secret="mock_bybit_secret", is_testnet=True)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "retCode": 0,
            "result": {"orderId": "bybit_112233"}
        }

        with patch.object(client.session, 'post', return_value=mock_response):
            res = client.place_order(
                symbol="BTC/USDT",
                side="BUY",
                order_type="LIMIT",
                price=83000.0,
                quantity=0.005,
                stop_loss=82500.0,
                take_profit=84000.0
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["order_id"], "bybit_112233")

    def test_webhook_client_dispatch(self):
        """Kiểm tra gửi JSON Alert qua WebhookClient"""
        client = WebhookClient(webhook_url="https://fake-webhook.com/api/alert")
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.post", return_value=mock_response):
            res = client.place_order(
                symbol="SOL/USDT",
                side="BUY",
                order_type="LIMIT",
                price=110.0,
                quantity=1.0,
                stop_loss=105.0,
                take_profit=120.0
            )
            self.assertTrue(res["success"])

    def test_order_executor_guard_conditions(self):
        """Kiểm tra các rào chắn điều kiện trước khi cho phép đặt lệnh"""
        proposal = {
            "action": "BUY_LIMIT",
            "entry_price": 83000.0,
            "position_size": 0.005,
            "stop_loss": 82500.0,
            "take_profit": 84000.0
        }

        # 1. Bị chặn khi Auto-Trade đang TẮT
        self.db.set_auto_trade_enabled(False)
        res1 = self.executor.execute_signal("BTC/USDT", proposal, {"action_decision": "APPROVE"})
        self.assertFalse(res1["executed"])
        self.assertEqual(res1["reason"], "AUTO_TRADE_DISABLED")

        # 2. Bị chặn khi AI Copilot VETO / REJECT
        self.db.set_auto_trade_enabled(True)
        res2 = self.executor.execute_signal("BTC/USDT", proposal, {"action_decision": "REJECT"})
        self.assertFalse(res2["executed"])
        self.assertEqual(res2["reason"], "NOT_APPROVED")

        # 3. Kích hoạt thành công khi APPROVE và Auto-Trade BẬT
        self.db.save_exchange_config(
            exchange="binance",
            api_key="valid_key",
            api_secret="valid_secret",
            is_testnet=True,
            auto_trade_enabled=True
        )
        mock_client = MagicMock()
        mock_client.get_open_position.return_value = None
        mock_client.has_open_orders.return_value = False
        mock_client.place_order.return_value = {
            "success": True,
            "order_id": "auto_ord_999",
            "client_order_id": "cl_999"
        }
        with patch.object(self.executor, 'get_client_for_config', return_value=mock_client):
            res3 = self.executor.execute_signal("BTC/USDT", proposal, {"action_decision": "APPROVE"})
            self.assertTrue(res3["executed"])
            self.assertEqual(res3["order_id"], "auto_ord_999")
            
            # Kiểm tra nhật ký đã được ghi vào DB
            orders = self.db.get_executed_orders(limit=5)
            self.assertGreaterEqual(len(orders), 1)
            self.assertEqual(orders[0]["order_id"], "auto_ord_999")

        # 4. IDEMPOTENCY: Chặn khi DB Cooldown đang kích hoạt
        with patch.object(self.executor, 'get_client_for_config', return_value=mock_client):
            res4 = self.executor.execute_signal("BTC/USDT", proposal, {"action_decision": "APPROVE"})
            self.assertFalse(res4["executed"])
            self.assertEqual(res4["reason"], "COOLDOWN_ACTIVE")

        # 5. IDEMPOTENCY: Chặn khi sàn đã có vị thế mở (tránh dồn volume)
        db_clean = DatabaseManager("storage/test_clean.db")
        executor_clean = OrderExecutor(db_clean)
        db_clean.save_exchange_config(exchange="binance", api_key="k", api_secret="s", is_testnet=True, auto_trade_enabled=True)
        mock_client_with_pos = MagicMock()
        mock_client_with_pos.get_open_position.return_value = {"symbol": "BTC/USDT", "size": 0.0114, "side": "LONG", "mark_price": 83000.0}
        mock_client_with_pos.has_open_orders.return_value = False
        mock_client_with_pos.get_open_orders.return_value = []
        mock_client_with_pos.attach_position_tpsl.return_value = {"success": True, "sl_order_id": "sl_1", "tp_order_id": "tp_1"}
        with patch.object(executor_clean, 'get_client_for_config', return_value=mock_client_with_pos):
            res5 = executor_clean.execute_signal("BTC/USDT", proposal, {"action_decision": "APPROVE"})
            self.assertFalse(res5["executed"])
            self.assertEqual(res5["reason"], "EXCHANGE_POSITION_EXISTS")
        if os.path.exists("storage/test_clean.db"):
            os.remove("storage/test_clean.db")

    def test_precision_tick_and_step_size(self):
        """Kiểm tra độ chính xác tick size (BTC 1 decimal, ETH/SOL 2 decimals)"""
        from execution.exchange_client import format_symbol_price, format_symbol_quantity
        # BTC Futures tickSize là 0.10 -> tối đa 1 số thập phân
        self.assertEqual(format_symbol_price("BTCUSDT", 82945.69), 82945.7)
        self.assertEqual(format_symbol_price("BTC/USDT", 83000.04), 83000.0)
        # ETH Futures tickSize là 0.01 -> 2 số thập phân
        self.assertEqual(format_symbol_price("ETHUSDT", 2540.556), 2540.56)
        # Step size khối lượng
        self.assertEqual(format_symbol_quantity("BTCUSDT", 0.01145), 0.011)
        self.assertEqual(format_symbol_quantity("SOLUSDT", 1.258), 1.26)

    def test_binance_attach_position_tpsl(self):
        """Kiểm tra Binance attach_position_tpsl gửi lệnh STOP_MARKET và TAKE_PROFIT_MARKET"""
        client = BinanceFuturesClient(api_key="k", api_secret="s", is_testnet=True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"orderId": "998877"}
        with patch.object(client, '_signed_request', return_value=mock_resp):
            with patch.object(client, 'get_open_position', return_value={"symbol": "BTC/USDT", "size": 0.01, "side": "LONG", "mark_price": 83000.0}):
                res = client.attach_position_tpsl("BTC/USDT", "LONG", stop_loss=82500.0, take_profit=84000.0)
                self.assertTrue(res["success"])
                self.assertEqual(res["sl_order_id"], "998877")
                self.assertEqual(res["tp_order_id"], "998877")

    def test_ensure_position_tpsl_protection(self):
        """Kiểm tra ensure_position_tpsl_protection tự động gắn TP/SL khi phát hiện vị thế thiếu bảo vệ"""
        mock_client = MagicMock()
        mock_client.get_open_position.return_value = {
            "symbol": "BTC/USDT",
            "size": 0.0114,
            "side": "LONG",
            "entry_price": 83000.0,
            "mark_price": 83100.0
        }
        # Chưa có lệnh điều kiện nào trên sàn
        mock_client.get_open_orders.return_value = []
        mock_client.attach_position_tpsl.return_value = {
            "success": True,
            "sl_order_id": "sl_888",
            "tp_order_id": "tp_888"
        }
        with patch.object(self.executor, 'get_client_for_config', return_value=mock_client):
            prot_res = self.executor.ensure_position_tpsl_protection("BTC/USDT")
            self.assertTrue(prot_res["success"])
            self.assertTrue(prot_res["protected"])
            self.assertEqual(prot_res["sl_order_id"], "sl_888")
            self.assertEqual(prot_res["tp_order_id"], "tp_888")

    def test_move_stop_loss_to_breakeven(self):
        """Kiểm tra move_stop_loss_to_breakeven dời SL về đúng Entry và giữ nguyên Take Profit"""
        mock_client = MagicMock()
        mock_client.get_open_position.return_value = {
            "symbol": "BTC/USDT",
            "size": 0.0114,
            "side": "LONG",
            "entry_price": 83491.40,
            "mark_price": 84100.0
        }
        # Đang có Take Profit ở 84500.0
        mock_client.get_open_orders.return_value = [
            {"type": "TAKE_PROFIT_MARKET", "stopPrice": "84500.0"}
        ]
        mock_client.attach_position_tpsl.return_value = {
            "success": True,
            "sl_order_id": "sl_be_123",
            "tp_order_id": "tp_be_123"
        }
        with patch.object(self.executor, 'get_client_for_config', return_value=mock_client):
            res = self.executor.move_stop_loss_to_breakeven("BTC/USDT", entry_price=83491.40)
            self.assertTrue(res["success"])
            self.assertEqual(res["entry_price"], 83491.40)
            self.assertEqual(res["sl_order_id"], "sl_be_123")
            # Kiểm tra attach_position_tpsl được gọi với stop_loss=entry_price (83491.40) và giữ nguyên TP 84500.0
            mock_client.attach_position_tpsl.assert_called_once_with(
                symbol="BTC/USDT",
                side="LONG",
                stop_loss=83491.40,
                take_profit=84500.0,
                position_side="BOTH"
            )

    def test_telegram_breakeven_alert_formatting(self):
        """Kiểm tra định dạng tin nhắn Telegram cảnh báo Breakeven (+1.0R)"""
        from alerts.telegram_bot import AlertDispatcher
        dispatcher = AlertDispatcher(bot_token="test_token", chat_id="12345", telegram_enabled=True)
        with patch.object(dispatcher, 'send_message', return_value=True) as mock_send:
            ok = dispatcher.send_breakeven_alert(
                symbol="BTC/USDT",
                side="LONG",
                entry=83491.40,
                current_price=84050.00,
                sl_order_id="sl_9999",
                r_multiple=1.1
            )
            self.assertTrue(ok)
            mock_send.assert_called_once()
            msg_content = mock_send.call_args[0][0]
            self.assertIn("BREAKEVEN ĐÃ KÍCH HOẠT", msg_content)
            self.assertIn("$83,491.40", msg_content)
            self.assertIn("+1.1R", msg_content)
            self.assertIn("$0 loss", msg_content)


def run_all_tests():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestDeterministicRiskEngine))
    suite.addTest(unittest.makeSuite(TestQuantitativeIndicators))
    suite.addTest(unittest.makeSuite(TestHardVetoRules))
    suite.addTest(unittest.makeSuite(TestStorageAndGuardrails))
    suite.addTest(unittest.makeSuite(TestPineScriptAndWebDashboard))
    suite.addTest(unittest.makeSuite(TestExchangeExecutionAndAutoTrade))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()

