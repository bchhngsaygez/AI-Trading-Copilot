"""
guardrails/risk_guardrails.py
Chương 5: Bộ Quy Tắc Rủi Ro & Bảo Vệ Tài Khoản (Guardrails)
4 Vòng Bảo Vệ Bất Khả Xâm Phạm Của Hệ Thống:
1. Daily Loss Circuit Breaker: Lỗ lũy kế >= $4.00 (2% vốn) -> Khóa 24h
2. Max Open Positions: Tối đa 2 vị thế đang chạy đồng thời
3. Risk-Free Breakeven Rule: Lãi >= 1.0R ($2.00) -> Tự động đôn SL về Entry
4. Anti-Tilt Cooldown: 2 SL liên tiếp -> Dừng quét 60 phút làm nguội tâm lý
"""

import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List, Optional

from storage.database import DatabaseManager

logger = logging.getLogger("Guardrails")


class RiskGuardrails:
    """
    Hệ Thống Rào Chắn Rủi Ro 4 Lớp Bảo Vệ Vốn Tuyệt Đối.
    """
    def __init__(
        self,
        db: DatabaseManager,
        daily_loss_limit_usd: float = 4.00,
        max_open_positions: int = 2,
        breakeven_trigger_r: float = 1.0,
        anti_tilt_consecutive_losses: int = 2,
        cooldown_minutes: int = 60
    ):
        self.db = db
        self.daily_loss_limit_usd = daily_loss_limit_usd
        self.max_open_positions = max_open_positions
        self.breakeven_trigger_r = breakeven_trigger_r
        self.anti_tilt_consecutive_losses = anti_tilt_consecutive_losses
        self.cooldown_seconds = cooldown_minutes * 60

        # Trạng thái Cooldown trong bộ nhớ (kèm timestamp hết hạn)
        self.cooldown_active_until: float = 0.0
        self.daily_lockout_active_until: float = 0.0

    def update_daily_loss_limit(self, limit_usd: float):
        """Cập nhật giới hạn ngắt mạch hàng ngày (2% vốn mới)"""
        self.daily_loss_limit_usd = float(limit_usd)

    def check_can_scan_and_propose(self) -> Tuple[bool, Optional[str]]:
        """
        Kiểm tra toàn diện 4 quy tắc trước khi cho phép quét hoặc đề xuất lệnh mới:
        Trả về (can_proceed: bool, reason_if_blocked: str)
        """
        now = time.time()

        # -------------------------------------------------------------
        # 1. KIỂM TRA DAILY LOSS CIRCUIT BREAKER
        # -------------------------------------------------------------
        if now < self.daily_lockout_active_until:
            rem_hrs = round((self.daily_lockout_active_until - now) / 3600.0, 1)
            return False, f"DAILY LOSS LOCKOUT: Đã chạm ngưỡng ngắt mạch 2% vốn ($4.00). Khóa hệ thống thêm {rem_hrs} giờ."

        daily_pnl = self.db.get_daily_realized_pnl()
        if daily_pnl <= -self.daily_loss_limit_usd:
            # Khóa 24 giờ
            self.daily_lockout_active_until = now + (24 * 3600)
            msg = f"KÍCH HOẠT DAILY LOSS CIRCUIT BREAKER! Lỗ trong ngày: ${daily_pnl:.2f} (Vượt ${self.daily_loss_limit_usd:.2f}). Khóa quyền phát tín hiệu 24h để bảo toàn vốn."
            logger.error(msg)
            self.db.log_audit_event("DAILY_CIRCUIT_BREAKER", msg, {"daily_pnl": daily_pnl})
            return False, msg

        # -------------------------------------------------------------
        # 2. KIỂM TRA ANTI-TILT COOLDOWN (2 LỆNH SL LIÊN TIẾP)
        # -------------------------------------------------------------
        if now < self.cooldown_active_until:
            rem_mins = int((self.cooldown_active_until - now) / 60)
            return False, f"ANTI-TILT COOLDOWN ĐANG BẬT: Vừa dính 2 SL liên tiếp. Tạm dừng quét {rem_mins} phút để làm nguội tâm lý."

        consecutive_losses = self.db.get_consecutive_losses()
        if consecutive_losses >= self.anti_tilt_consecutive_losses:
            self.cooldown_active_until = now + self.cooldown_seconds
            msg = f"KÍCH HOẠT ANTI-TILT COOLDOWN: Dính {consecutive_losses} lệnh thua liên tiếp. Tắt scanner trong {self.cooldown_seconds // 60} phút."
            logger.warning(msg)
            self.db.log_audit_event("ANTI_TILT_COOLDOWN", msg, {"consecutive_losses": consecutive_losses})
            return False, msg

        # -------------------------------------------------------------
        # 3. KIỂM TRA MAX OPEN POSITIONS
        # -------------------------------------------------------------
        open_count = self.db.get_active_positions_count()
        if open_count >= self.max_open_positions:
            return False, f"MAX OPEN POSITIONS: Đang có {open_count}/{self.max_open_positions} vị thế mở. Từ chối tìm cơ hội mới."

        return True, None

    def check_and_update_breakeven(self, current_prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        Quy tắc Risk-Free Breakeven:
        Rà soát các vị thế đang mở. Nếu lợi nhuận chưa chốt đạt >= 1.0R (>= $2.00),
        tự động đôn Stop Loss về đúng giá Entry ban đầu (Rủi ro = $0.00).
        """
        active_positions = self.db.get_active_positions()
        updates: List[Dict[str, Any]] = []

        for pos in active_positions:
            pos_id = pos["id"]
            symbol = pos["symbol"]
            side = pos["side"]
            entry = pos["entry_price"]
            orig_sl = pos["original_sl"]
            curr_sl = pos["current_sl"]
            is_be = pos["is_breakeven"]

            if is_be:
                continue  # Đã dời hòa vốn rồi

            curr_price = current_prices.get(symbol)
            if not curr_price:
                continue

            # Tính khoảng cách 1.0R theo giá (khoảng cách rủi ro ban đầu)
            r_distance = abs(entry - orig_sl)
            if r_distance <= 0:
                # Nếu không có orig_sl hợp lệ, giả định mặc định 1.5% theo ATR
                r_distance = entry * 0.015

            achieved_breakeven = False
            r_multiple = 0.0
            if side == "LONG":
                # Lãi khi giá vượt Entry + 1.0R
                r_multiple = round((curr_price - entry) / r_distance, 2)
                if r_multiple >= 1.0:
                    achieved_breakeven = True
            elif side == "SHORT":
                # Lãi khi giá giảm dưới Entry - 1.0R
                r_multiple = round((entry - curr_price) / r_distance, 2)
                if r_multiple >= 1.0:
                    achieved_breakeven = True

            if achieved_breakeven:
                logger.info(f"⚡ [BREAKEVEN] Đạt mốc +{r_multiple}R (>= 1.0R) cho {symbol} {side}! Tự động đôn SL từ {curr_sl} về Entry {entry} (Risk-Free).")
                self.db.update_position_sl_to_breakeven(pos_id, entry)
                self.db.log_audit_event(
                    "RISK_FREE_BREAKEVEN",
                    f"Đôn SL về Entry {entry} cho {symbol} {side} khi giá đạt {curr_price} (+{r_multiple}R).",
                    {
                        "position_id": pos_id,
                        "symbol": symbol,
                        "entry": entry,
                        "current_price": curr_price,
                        "r_multiple": r_multiple,
                        "r_distance": r_distance
                    }
                )
                updates.append({
                    "position_id": pos_id,
                    "symbol": symbol,
                    "side": side,
                    "entry": entry,
                    "current_price": curr_price,
                    "r_distance": r_distance,
                    "r_multiple": r_multiple,
                    "status": "SL_MOVED_TO_BREAKEVEN"
                })

        return updates

    def get_guardrails_status_report(self) -> Dict[str, Any]:
        """Tạo báo cáo tình trạng các lớp bảo vệ tài khoản"""
        now = time.time()
        daily_pnl = self.db.get_daily_realized_pnl()
        open_count = self.db.get_active_positions_count()
        consecutive_losses = self.db.get_consecutive_losses()

        is_daily_locked = (now < self.daily_lockout_active_until) or (daily_pnl <= -self.daily_loss_limit_usd)
        is_cooldown = (now < self.cooldown_active_until)

        return {
            "daily_pnl_usd": round(daily_pnl, 2),
            "daily_loss_limit_usd": self.daily_loss_limit_usd,
            "daily_circuit_breaker_active": is_daily_locked,
            "active_positions_count": open_count,
            "max_open_positions_allowed": self.max_open_positions,
            "consecutive_losses_count": consecutive_losses,
            "anti_tilt_cooldown_active": is_cooldown,
            "can_trade": not (is_daily_locked or is_cooldown or open_count >= self.max_open_positions)
        }
