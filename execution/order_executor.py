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
            # Luôn kiểm tra và bảo đảm vị thế trên sàn phải có TP/SL
            self.ensure_position_tpsl_protection(symbol, target_sl=stop_loss, target_tp=take_profit)
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
            self.ensure_position_tpsl_protection(symbol, target_sl=stop_loss, target_tp=take_profit)

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

            # Đảm bảo TP/SL được kích hoạt nếu vị thế đã khớp
            self.ensure_position_tpsl_protection(symbol, target_sl=stop_loss, target_tp=take_profit)

        # 9. Ghi nhật ký vào SQLite Database
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

        # 10. Ghi sự kiện kiểm toán (Audit Log)
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

    def ensure_position_tpsl_protection(
        self,
        symbol: str,
        target_sl: Optional[float] = None,
        target_tp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Rà soát và đảm bảo vị thế đang mở trên sàn (Binance / Bybit) phải có TP/SL.
        Nếu phát hiện vị thế đang mở mà chưa có TP/SL (hoặc bị thiếu):
        Tự động lấy mức SL/TP từ DB (hoặc target truyền vào) và gọi attach_position_tpsl để kích hoạt cột 'TP/SL for position'.
        """
        cfg = self.db.get_exchange_config()
        client = self.get_client_for_config(cfg)
        if not client:
            return {"success": False, "message": "Chưa cấu hình API Key sàn"}

        try:
            pos = client.get_open_position(symbol)
            if not pos or pos.get("size", 0.0) <= 0:
                return {"success": True, "has_position": False, "message": f"Không có vị thế mở trên sàn cho {symbol}"}

            side = pos.get("side", "LONG")
            pos_side = pos.get("position_side", "BOTH")
            entry_price = float(pos.get("entry_price", 0.0))
            pos_size = float(pos.get("size", 0.0))

            # Kiểm tra xem trên sàn đã có lệnh STOP_MARKET và TAKE_PROFIT_MARKET chưa
            open_orders = client.get_open_orders(symbol)
            has_sl = any(o.get("type") in ("STOP_MARKET", "STOP") for o in open_orders)
            has_tp = any(o.get("type") in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT") for o in open_orders)

            if has_sl and has_tp and not target_sl and not target_tp:
                return {
                    "success": True,
                    "has_position": True,
                    "already_protected": True,
                    "message": f"Vị thế {symbol} ({side} {pos_size}) đã có đủ cả TP và SL trên sàn."
                }

            # Xác định mức giá SL và TP cần gắn
            sl = target_sl
            tp = target_tp

            # Nếu chưa có, tìm trong active_positions của SQLite nội bộ
            active_pos = self.db.get_active_positions()
            matched = next((p for p in active_pos if p.get("symbol") == symbol and p.get("status") == "OPEN"), None)
            if not sl or not tp:
                if matched:
                    sl = sl or matched.get("stop_loss")
                    tp = tp or matched.get("tp1") or matched.get("tp2")

            # Nếu vẫn chưa có SL/TP (ví dụ đặt thủ công), tính toán an toàn theo %
            is_btc = "BTC" in symbol.replace("/", "").upper()
            dec = 1 if is_btc else 2
            if not sl:
                sl = round(entry_price * 0.985, dec) if side == "LONG" else round(entry_price * 1.015, dec)
            if not tp:
                tp = round(entry_price * 1.03, dec) if side == "LONG" else round(entry_price * 0.97, dec)

            # Đồng bộ vị thế vào active_positions nếu chưa có để theo dõi Breakeven
            if not matched:
                try:
                    self.db.open_position(
                        signal_id=None,
                        symbol=symbol,
                        side=side,
                        entry_price=entry_price,
                        stop_loss=sl,
                        tp1=tp,
                        tp2=tp,
                        tp3=tp,
                        position_size=pos_size,
                        risk_usd=round(pos_size * abs(entry_price - sl), 2)
                    )
                except Exception as open_err:
                    logger.debug(f"Không thể tự động đồng bộ vị thế vào DB: {open_err}")

            logger.info(f"⚡ [AUTO-PROTECT] Tiến hành gắn TP/SL cho vị thế {symbol} ({side} {pos_size}): SL={sl}, TP={tp}")
            attach_res = client.attach_position_tpsl(
                symbol=symbol,
                side=side,
                stop_loss=sl,
                take_profit=tp,
                position_side=pos_side
            )

            if attach_res.get("success"):
                msg = f"Đã gắn thành công Position TP/SL cho {symbol} ({side} {pos_size}) trên sàn {cfg.get('exchange', '').upper()}!"
                logger.info(f"✅ {msg}")
                self.db.log_audit_event("AUTO_PROTECT_TPSL_ATTACHED", msg, {
                    "symbol": symbol,
                    "side": side,
                    "sl": sl,
                    "tp": tp,
                    "sl_order_id": str(attach_res.get("sl_order_id")),
                    "tp_order_id": str(attach_res.get("tp_order_id"))
                })
                return {
                    "success": True,
                    "has_position": True,
                    "protected": True,
                    "sl_order_id": attach_res.get("sl_order_id"),
                    "tp_order_id": attach_res.get("tp_order_id"),
                    "message": msg
                }
            else:
                err_msg = f"Không thể gắn TP/SL cho {symbol}: {attach_res.get('errors')}"
                logger.warning(f"⚠️ {err_msg}")
                return {
                    "success": False,
                    "has_position": True,
                    "message": err_msg,
                    "errors": attach_res.get("errors")
                }
        except Exception as e:
            logger.error(f"Lỗi khi bảo vệ TP/SL cho {symbol}: {e}")
            return {"success": False, "message": str(e)}

    def move_stop_loss_to_breakeven(self, symbol: str, entry_price: float) -> Dict[str, Any]:
        """
        Dời Stop Loss trên sàn giao dịch về đúng giá Entry (Hòa vốn / Zero Risk).
        Giữ nguyên Take Profit hiện tại của vị thế.
        """
        cfg = self.db.get_exchange_config()
        client = self.get_client_for_config(cfg)
        if not client:
            return {"success": False, "message": "Chưa cấu hình API Key sàn"}

        try:
            pos = client.get_open_position(symbol)
            if not pos or pos.get("size", 0.0) <= 0:
                return {"success": False, "message": f"Không có vị thế mở trên sàn cho {symbol}"}

            side = pos.get("side", "LONG")
            pos_side = pos.get("position_side", "BOTH")
            pos_size = float(pos.get("size", 0.0))

            # Tìm Take Profit hiện tại từ lệnh chờ trên sàn để không làm mất TP
            open_orders = client.get_open_orders(symbol)
            tp_price = None
            for o in open_orders:
                if isinstance(o, dict) and o.get("type") in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT"):
                    tp_price = float(o.get("stopPrice", 0.0))
                    break

            if not tp_price:
                active_pos = self.db.get_active_positions()
                matched = next((p for p in active_pos if p.get("symbol") == symbol and p.get("status") == "OPEN"), None)
                if matched:
                    tp_price = matched.get("tp1") or matched.get("tp2")

            # Gắn lại SL = entry_price và giữ nguyên TP
            logger.info(f"🛡️ [BREAKEVEN ON-EXCHANGE] Dời SL về Entry ${entry_price:,.2f} cho {symbol} ({side} {pos_size})...")
            attach_res = client.attach_position_tpsl(
                symbol=symbol,
                side=side,
                stop_loss=entry_price,
                take_profit=tp_price,
                position_side=pos_side
            )

            if attach_res.get("success"):
                msg = f"Đã dời SL về hòa vốn ${entry_price:,.2f} thành công cho {symbol} trên sàn {cfg.get('exchange', '').upper()} (Order #{attach_res.get('sl_order_id')})!"
                logger.info(f"✅ {msg}")
                self.db.log_audit_event("BREAKEVEN_STOP_LOSS_UPDATED_ON_EXCHANGE", msg, {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "tp_price": tp_price,
                    "sl_order_id": str(attach_res.get("sl_order_id")),
                    "tp_order_id": str(attach_res.get("tp_order_id"))
                })
                return {
                    "success": True,
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "sl_order_id": attach_res.get("sl_order_id"),
                    "tp_order_id": attach_res.get("tp_order_id"),
                    "message": msg
                }
            else:
                err_msg = f"Lỗi dời SL về Breakeven cho {symbol}: {attach_res.get('errors')}"
                logger.warning(f"⚠️ {err_msg}")
                return {"success": False, "message": err_msg}
        except Exception as e:
            logger.error(f"Lỗi khi dời SL về Breakeven cho {symbol}: {e}")
            return {"success": False, "message": str(e)}

    def sync_active_positions_tpsl(self, symbol: str, stop_loss: float, take_profit: float):
        """Đồng bộ định kỳ alias cho ensure_position_tpsl_protection"""
        return self.ensure_position_tpsl_protection(symbol, target_sl=stop_loss, target_tp=take_profit)

