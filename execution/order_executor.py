"""
execution/order_executor.py
Bộ điều phối tự động khớp lệnh khi AI ra quyết định APPROVE (Automated Order Executor)
- Tự động nạp cấu hình sàn giao dịch từ SQLite Database
- Điều phối đặt lệnh Limit Order theo giá Entry được tính toán
- Tự động gắn kèm Stop Loss (đệm ATR 1.2x - 1.5x) và Take Profit (R:R 1:2.0)
- Ghi nhật ký vào bảng executed_orders và audit_log
"""

import logging
from typing import Dict, Any, Optional

from storage.database import DatabaseManager
from execution.exchange_client import (
    BinanceFuturesClient,
    BybitPerpetualClient,
    WebhookClient,
    BaseExchangeClient
)

logger = logging.getLogger("OrderExecutor")


class OrderExecutor:
    """
    Quản lý luồng tự động đặt lệnh khi có tín hiệu APPROVE từ AI Copilot.
    """
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_client_for_config(self, cfg: Dict[str, Any]) -> Optional[BaseExchangeClient]:
        """Khởi tạo Exchange Client tương ứng theo cấu hình người dùng"""
        exchange = cfg.get("exchange", "binance").lower().strip()
        api_key = cfg.get("api_key", "").strip()
        api_secret = cfg.get("api_secret", "").strip()
        is_testnet = bool(cfg.get("is_testnet", True))
        webhook_url = cfg.get("webhook_url", "").strip()

        if exchange == "binance":
            if not api_key or not api_secret:
                return None
            return BinanceFuturesClient(api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)
        elif exchange == "bybit":
            if not api_key or not api_secret:
                return None
            return BybitPerpetualClient(api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)
        elif exchange == "webhook":
            if not webhook_url:
                return None
            return WebhookClient(webhook_url=webhook_url)

        return None

    def execute_signal(
        self,
        symbol: str,
        proposal: Dict[str, Any],
        ai_result: Dict[str, Any],
        signal_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Thực hiện đặt lệnh tự động nếu cờ Auto-Trade đang bật.
        """
        # 1. Kiểm tra cờ Auto-Trade
        if not self.db.is_auto_trade_enabled():
            return {
                "executed": False,
                "reason": "AUTO_TRADE_DISABLED",
                "message": "Tính năng tự động đặt lệnh hiện đang TẮT. Đã bỏ qua bước khớp lệnh."
            }

        # 2. Kiểm tra quyết định AI (Bắt buộc phải là APPROVE)
        decision = ai_result.get("action_decision", "")
        if decision != "APPROVE":
            return {
                "executed": False,
                "reason": "NOT_APPROVED",
                "message": f"Quyết định AI là {decision}, không đủ điều kiện tự động đặt lệnh."
            }

        # 3. Lấy cấu hình sàn giao dịch
        cfg = self.db.get_exchange_config()
        client = self.get_client_for_config(cfg)
        exchange_name = cfg.get("exchange", "binance")
        is_testnet = cfg.get("is_testnet", True)

        if not client:
            msg = f"Chưa cấu hình API Key/Secret hợp lệ cho sàn {exchange_name.upper()}."
            logger.warning(f"AUTO-TRADE BỎ QUA: {msg}")
            self.db.log_audit_event("AUTO_TRADE_SKIPPED", msg, {"signal_id": signal_id})
            return {
                "executed": False,
                "reason": "MISSING_API_CREDENTIALS",
                "message": msg
            }

        # 4. Trích xuất thông số toán học từ Position Proposal
        action = proposal.get("action", "BUY_LIMIT")
        side = "BUY" if "BUY" in action.upper() else "SELL"
        order_type = "LIMIT"
        entry_price = float(proposal.get("entry_price", 0.0))
        position_size = float(proposal.get("position_size", 0.0))
        stop_loss = float(proposal.get("stop_loss", 0.0))
        take_profit = float(proposal.get("take_profit", 0.0))

        if entry_price <= 0 or position_size <= 0:
            return {
                "executed": False,
                "reason": "INVALID_PROPOSAL_PARAMS",
                "message": f"Thông số lệnh không hợp lệ: Entry={entry_price}, Size={position_size}"
            }

        logger.info(
            f"🚀 [AUTO-TRADE EXECUTION] Bắt đầu đặt lệnh {action} {symbol} "
            f"tại ${entry_price:,.2f} | Size: {position_size} | Sàn: {exchange_name.upper()} "
            f"({'Testnet' if is_testnet else 'MAINNET REAL'})..."
        )

        # 5. Gửi lệnh lên sàn qua Exchange Client
        res = client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=entry_price,
            quantity=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        status = "SUBMITTED" if res.get("success") else "FAILED"
        order_id = res.get("order_id")
        client_oid = res.get("client_order_id")
        sl_oid = res.get("sl_order_id")
        tp_oid = res.get("tp_order_id")
        err_msg = res.get("error")

        # 6. Ghi nhật ký vào SQLite Database
        exec_id = self.db.record_executed_order(
            signal_id=signal_id,
            exchange=exchange_name,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=entry_price,
            quantity=position_size,
            order_id=order_id,
            client_order_id=client_oid,
            status=status,
            sl_order_id=sl_oid,
            tp_order_id=tp_oid,
            is_testnet=is_testnet,
            error_message=err_msg,
            raw_response=res
        )

        # 7. Ghi sự kiện kiểm toán (Audit Log)
        audit_desc = (
            f"Tự động đặt lệnh thành công: {side} {symbol} tại ${entry_price:,.2f} (Order #{order_id})"
            if res.get("success")
            else f"Tự động đặt lệnh thất bại: {side} {symbol} (Lỗi: {err_msg})"
        )
        self.db.log_audit_event("AUTO_ORDER_EXECUTION", audit_desc, {
            "executed_order_id": exec_id,
            "signal_id": signal_id,
            "exchange": exchange_name,
            "is_testnet": is_testnet,
            "result": res
        })

        return {
            "executed": res.get("success", False),
            "executed_order_id": exec_id,
            "exchange": exchange_name,
            "is_testnet": is_testnet,
            "order_id": order_id,
            "sl_order_id": sl_oid,
            "tp_order_id": tp_oid,
            "status": status,
            "message": audit_desc,
            "raw": res
        }
