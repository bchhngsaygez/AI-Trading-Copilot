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

        # 5. IDEMPOTENCY GUARD 1: Kiểm tra Cooldown & Vị thế mở trong SQLite nội bộ
        if self.db.has_active_position_or_recent_order(symbol, cooldown_minutes=15):
            msg = f"Cặp {symbol} đã có vị thế mở hoặc vừa gửi lệnh trong 15 phút qua. Bỏ qua đặt lệnh lặp lại để chống dồn khối lượng."
            logger.info(f"🛡️ [IDEMPOTENCY GUARD] {msg}")
            return {
                "executed": False,
                "reason": "COOLDOWN_ACTIVE",
                "message": msg
            }

        # 6. IDEMPOTENCY GUARD 2: Kiểm tra Vị thế thực tế và Lệnh chờ trực tiếp trên sàn
        pos_on_exchange = client.get_open_position(symbol)
        if pos_on_exchange and pos_on_exchange.get("size", 0.0) > 0:
            msg = f"Sàn {exchange_name.upper()} đã có vị thế đang mở cho {symbol} ({pos_on_exchange.get('size')} {symbol}). Hủy trigger để chống dồn volume."
            logger.warning(f"🛡️ [IDEMPOTENCY GUARD] {msg}")
            self.db.log_audit_event("AUTO_TRADE_BLOCKED_EXISTING_POSITION", msg, {"symbol": symbol, "position": pos_on_exchange})

            # Tự động gắn SL/TP cho vị thế hiện có nếu trước đó bị thiếu
            if stop_loss > 0 or take_profit > 0:
                client.attach_position_tpsl(symbol, pos_on_exchange.get("side", side), stop_loss, take_profit)

            return {
                "executed": False,
                "reason": "EXCHANGE_POSITION_EXISTS",
                "message": msg
            }

        if client.has_open_orders(symbol):
            msg = f"Sàn {exchange_name.upper()} đang có lệnh chờ (Pending Limit / Stop) cho {symbol}. Hủy trigger để tránh lặp lệnh."
            logger.warning(f"🛡️ [IDEMPOTENCY GUARD] {msg}")
            return {
                "executed": False,
                "reason": "EXCHANGE_PENDING_ORDER_EXISTS",
                "message": msg
            }

        logger.info(
            f"🚀 [AUTO-TRADE EXECUTION] Bắt đầu đặt lệnh {action} {symbol} "
            f"tại ${entry_price:,.2f} | Size: {position_size} | Sàn: {exchange_name.upper()} "
            f"({'Testnet' if is_testnet else 'MAINNET REAL'})..."
        )

        # 7. Gửi lệnh lên sàn qua Exchange Client
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

        # 8. Mở vị thế theo dõi trong active_positions nếu lệnh đặt thành công
        if res.get("success") and signal_id:
            try:
                tp1_val = proposal.get("tp1", {}).get("price", take_profit) if isinstance(proposal.get("tp1"), dict) else take_profit
                tp2_val = proposal.get("tp2", {}).get("price", take_profit) if isinstance(proposal.get("tp2"), dict) else take_profit
                tp3_val = proposal.get("tp3", {}).get("price", take_profit) if isinstance(proposal.get("tp3"), dict) else take_profit
                self.db.open_position(
                    signal_id=signal_id,
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    tp1=tp1_val,
                    tp2=tp2_val,
                    tp3=tp3_val,
                    position_size=position_size,
                    risk_usd=proposal.get("risk_amount_usd", 2.0)
                )
            except Exception as pos_err:
                logger.warning(f"Lỗi mở vị thế trong DB: {pos_err}")

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

    def sync_active_positions_tpsl(self, symbol: str, stop_loss: float, take_profit: float):
        """
        Đồng bộ định kỳ: Nếu trên sàn có vị thế đang mở mà chưa gắn SL/TP,
        tự động gắn SL/TP vào vị thế ngay để không bao giờ bị trống cột 'TP/SL for position'.
        """
        cfg = self.db.get_exchange_config()
        client = self.get_client_for_config(cfg)
        if not client:
            return
        try:
            pos = client.get_open_position(symbol)
            if pos and pos.get("size", 0.0) > 0:
                client.attach_position_tpsl(symbol, pos.get("side", "LONG"), stop_loss, take_profit)
        except Exception as e:
            logger.debug(f"Lỗi sync SL/TP cho {symbol}: {e}")

