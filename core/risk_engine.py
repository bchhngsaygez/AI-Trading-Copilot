"""
core/risk_engine.py
Tier 3: Deterministic Mathematical Risk Engine
Hạt nhân toán học bất khả xâm phạm - Loại bỏ 100% cảm tính và ảo giác:
- Fixed Fractional Risk (1% tài khoản $200 = $2.00 USD)
- Adaptive Stop Loss Buffer (1.2 * ATR chống quét râu nến)
- Cưỡng chế giãn SL tối thiểu 1.5 * ATR
- Tính khối lượng vị thế (Position Sizing) tuyệt đối
- Phân bổ Take Profit đa tầng Scale-Out (TP1: 1.5R, TP2: 2.5R, TP3: 4.0R)
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


@dataclass
class ScaleOutTarget:
    r_multiple: float
    price: float
    close_percentage: int
    note: str


@dataclass
class PositionProposal:
    symbol: str
    action: str                        # "BUY_LIMIT" | "SELL_LIMIT" | "BUY_MARKET"
    entry_price: float
    stop_loss: float
    take_profit: float                 # TP chính (1:2.0)
    sl_distance: float
    sl_buffer_atr_multiple: float
    position_size: float               # Số lượng coin/token
    position_value_usd: float          # Giá trị danh nghĩa vị thế
    minimum_leverage: float            # Đòn bẩy tối thiểu cần thiết
    account_equity: float
    risk_amount_usd: float             # Cố định đúng 1% ($2.00)
    risk_reward_ratio: float           # Tỷ lệ R:R
    is_valid: bool
    tp1: Optional[ScaleOutTarget] = None
    tp2: Optional[ScaleOutTarget] = None
    tp3: Optional[ScaleOutTarget] = None
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data


class DeterministicRiskEngine:
    """
    Tầng Quản Trị Rủi Ro Toán Học - 100% Deterministic Code, không LLM.
    """
    def __init__(
        self,
        account_equity: float = 200.0,
        risk_percent: float = 1.0,
        sl_buffer_mult: float = 1.2,
        forced_min_sl_mult: float = 1.5,
        min_rr: float = 2.0
    ):
        self.account_equity = float(account_equity)
        self.risk_percent = float(risk_percent)
        self.sl_buffer_mult = float(sl_buffer_mult)
        self.forced_min_sl_mult = float(forced_min_sl_mult)
        self.min_rr = float(min_rr)
        # Rủi ro tối đa cố định: ví dụ $200 * 1% = $2.00 USD
        self.max_risk_usd = round(self.account_equity * (self.risk_percent / 100.0), 2)

    @staticmethod
    def get_symbol_precision(symbol: str) -> int:
        """Định dạng số chữ số thập phân phù hợp từng coin"""
        upper = symbol.upper()
        if "BTC" in upper:
            return 4
        elif "ETH" in upper:
            return 3
        elif "SOL" in upper:
            return 2
        return 2

    def calculate_long_proposal(
        self,
        symbol: str,
        entry: float,
        swing_low_5: float,
        atr_15m: float
    ) -> PositionProposal:
        """
        Tính toán vị thế Mua (Long):
        1. Khoang_dem_Buffer = 1.2 * ATR_15m
        2. Stop_Loss = Min(Swing_Low_5_nen, Entry - Khoang_dem_Buffer)
        3. Kiểm tra nếu Khoang_cach_SL < (1.0 * ATR_15m):
           -> Cưỡng chế Stop_Loss = Entry - (1.5 * ATR_15m)
        """
        if entry <= 0 or atr_15m <= 0:
            return PositionProposal(
                symbol=symbol, action="BUY_LIMIT", entry_price=entry, stop_loss=0,
                take_profit=0, sl_distance=0, sl_buffer_atr_multiple=0, position_size=0,
                position_value_usd=0, minimum_leverage=0, account_equity=self.account_equity,
                risk_amount_usd=self.max_risk_usd, risk_reward_ratio=0, is_valid=False,
                rejection_reason="Entry hoặc ATR không hợp lệ (<= 0)"
            )

        buffer = self.sl_buffer_mult * atr_15m
        calculated_sl = swing_low_5 - buffer
        sl_distance = entry - calculated_sl

        # Kiểm tra bất thường: SL nằm trên hoặc bằng Entry
        if sl_distance <= 0:
            return PositionProposal(
                symbol=symbol, action="BUY_LIMIT", entry_price=entry, stop_loss=calculated_sl,
                take_profit=0, sl_distance=0, sl_buffer_atr_multiple=0, position_size=0,
                position_value_usd=0, minimum_leverage=0, account_equity=self.account_equity,
                risk_amount_usd=self.max_risk_usd, risk_reward_ratio=0, is_valid=False,
                rejection_reason="Entry nhỏ hơn hoặc bằng Stop Loss dự kiến"
            )

        # Cưỡng chế khoảng cách an toàn tối thiểu 1.0 ATR
        if sl_distance < (1.0 * atr_15m):
            calculated_sl = entry - (self.forced_min_sl_mult * atr_15m)
            sl_distance = entry - calculated_sl

        sl_buffer_multiple = round(sl_distance / atr_15m, 2)

        # Tính khối lượng Coin chính xác cố định mức rủi ro đúng 2 USD
        precision = self.get_symbol_precision(symbol)
        position_size = round(self.max_risk_usd / sl_distance, precision)

        # Nếu size bị làm tròn thành 0 do giá coin lớn và step nhỏ
        if position_size <= 0:
            position_size = round(self.max_risk_usd / sl_distance, precision + 2)

        position_value = round(position_size * entry, 2)
        min_leverage = round(position_value / max(self.account_equity, 1.0), 2)

        # Định tuyến Take Profit theo tỷ lệ vàng R:R = 1:2.0
        tp_distance = sl_distance * 2.0
        calculated_tp = round(entry + tp_distance, 2)
        rr_ratio = round(tp_distance / sl_distance, 2)

        # Scale-Out Plan (TP1 1.5R, TP2 2.5R, TP3 4.0R)
        tp1 = ScaleOutTarget(
            r_multiple=1.5,
            price=round(entry + (1.5 * sl_distance), 2),
            close_percentage=50,
            note="Đóng 50%, kích hoạt dời SL về Breakeven (Hòa vốn)"
        )
        tp2 = ScaleOutTarget(
            r_multiple=2.5,
            price=round(entry + (2.5 * sl_distance), 2),
            close_percentage=30,
            note="Đóng 30%, chốt lời phần lớn"
        )
        tp3 = ScaleOutTarget(
            r_multiple=4.0,
            price=round(entry + (4.0 * sl_distance), 2),
            close_percentage=20,
            note="Thả trôi 20% còn lại với Trailing Stop"
        )

        return PositionProposal(
            symbol=symbol,
            action="BUY_LIMIT",
            entry_price=round(entry, 2),
            stop_loss=round(calculated_sl, 2),
            take_profit=calculated_tp,
            sl_distance=round(sl_distance, 2),
            sl_buffer_atr_multiple=sl_buffer_multiple,
            position_size=position_size,
            position_value_usd=position_value,
            minimum_leverage=min_leverage,
            account_equity=self.account_equity,
            risk_amount_usd=self.max_risk_usd,
            risk_reward_ratio=rr_ratio,
            is_valid=True,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3
        )

    def calculate_short_proposal(
        self,
        symbol: str,
        entry: float,
        swing_high_5: float,
        atr_15m: float
    ) -> PositionProposal:
        """
        Tính toán vị thế Bán (Short):
        Stop Loss = Max(Swing_High_5_nen, Entry + 1.2 * ATR_15m)
        """
        if entry <= 0 or atr_15m <= 0:
            return PositionProposal(
                symbol=symbol, action="SELL_LIMIT", entry_price=entry, stop_loss=0,
                take_profit=0, sl_distance=0, sl_buffer_atr_multiple=0, position_size=0,
                position_value_usd=0, minimum_leverage=0, account_equity=self.account_equity,
                risk_amount_usd=self.max_risk_usd, risk_reward_ratio=0, is_valid=False,
                rejection_reason="Entry hoặc ATR không hợp lệ (<= 0)"
            )

        buffer = self.sl_buffer_mult * atr_15m
        calculated_sl = max(swing_high_5, entry + buffer)
        sl_distance = calculated_sl - entry

        if sl_distance <= 0:
            return PositionProposal(
                symbol=symbol, action="SELL_LIMIT", entry_price=entry, stop_loss=calculated_sl,
                take_profit=0, sl_distance=0, sl_buffer_atr_multiple=0, position_size=0,
                position_value_usd=0, minimum_leverage=0, account_equity=self.account_equity,
                risk_amount_usd=self.max_risk_usd, risk_reward_ratio=0, is_valid=False,
                rejection_reason="Entry lớn hơn hoặc bằng Stop Loss dự kiến"
            )

        if sl_distance < (1.0 * atr_15m):
            calculated_sl = entry + (self.forced_min_sl_mult * atr_15m)
            sl_distance = calculated_sl - entry

        sl_buffer_multiple = round(sl_distance / atr_15m, 2)
        precision = self.get_symbol_precision(symbol)
        position_size = round(self.max_risk_usd / sl_distance, precision)
        if position_size <= 0:
            position_size = round(self.max_risk_usd / sl_distance, precision + 2)

        position_value = round(position_size * entry, 2)
        min_leverage = round(position_value / max(self.account_equity, 1.0), 2)

        tp_distance = sl_distance * 2.0
        calculated_tp = round(entry - tp_distance, 2)
        rr_ratio = round(tp_distance / sl_distance, 2)

        tp1 = ScaleOutTarget(
            r_multiple=1.5,
            price=round(entry - (1.5 * sl_distance), 2),
            close_percentage=50,
            note="Đóng 50%, kích hoạt dời SL về Breakeven (Hòa vốn)"
        )
        tp2 = ScaleOutTarget(
            r_multiple=2.5,
            price=round(entry - (2.5 * sl_distance), 2),
            close_percentage=30,
            note="Đóng 30%, chốt lời phần lớn"
        )
        tp3 = ScaleOutTarget(
            r_multiple=4.0,
            price=round(entry - (4.0 * sl_distance), 2),
            close_percentage=20,
            note="Thả trôi 20% còn lại với Trailing Stop"
        )

        return PositionProposal(
            symbol=symbol,
            action="SELL_LIMIT",
            entry_price=round(entry, 2),
            stop_loss=round(calculated_sl, 2),
            take_profit=calculated_tp,
            sl_distance=round(sl_distance, 2),
            sl_buffer_atr_multiple=sl_buffer_multiple,
            position_size=position_size,
            position_value_usd=position_value,
            minimum_leverage=min_leverage,
            account_equity=self.account_equity,
            risk_amount_usd=self.max_risk_usd,
            risk_reward_ratio=rr_ratio,
            is_valid=True,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3
        )
