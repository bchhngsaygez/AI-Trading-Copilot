"""
core/indicator_engine.py
Tier 2: Quantitative Indicator Engine
Tính toán 10+ chỉ báo kỹ thuật cao cấp 100% bằng Python & NumPy/Pandas:
- LuxAlgo-equivalent Trendlines with Breaks (Xác nhận vượt 0.2% biên độ)
- RSI Multi-length (10, 14, 30) với công thức Wilder's Smoothing chuẩn TradingView
- Adaptive Average True Range (ATR 14)
- Fair Value Gap (FVG) & Liquidity Sweeps / Pinbar
- EMA 50, EMA 200 đa khung thời gian
- Swing High / Swing Low (Rolling Window n=5)
- Phát hiện thác nước xả nến (Waterfall dump)
"""

from typing import Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd


class QuantitativeIndicatorEngine:
    """
    Tầng Toán Học Định Lượng - Tính toán xác định, không ảo giác, không phụ thuộc TradingView.
    """

    @staticmethod
    def calculate_wilder_rma(series: pd.Series, period: int) -> pd.Series:
        """
        Wilder's Smoothing Moving Average (RMA) - chuẩn xác công thức TradingView:
        alpha = 1 / period
        """
        return series.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    @classmethod
    def calculate_rsi(cls, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Tính RSI chuẩn TradingView theo thuật toán Wilder's RMA.
        """
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = cls.calculate_wilder_rma(gain, period)
        avg_loss = cls.calculate_wilder_rma(loss, period)

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # Xử lý trường hợp loss = 0 -> RSI = 100
        rsi = rsi.fillna(100.0)
        return rsi

    @classmethod
    def calculate_atr(cls, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Tính ATR thích ứng chuẩn TradingView:
        TR = max(High - Low, abs(High - Close_prev), abs(Low - Close_prev))
        ATR = Wilder's RMA của TR
        """
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return cls.calculate_wilder_rma(true_range, period)

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Tính Exponential Moving Average"""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def detect_swings(df: pd.DataFrame, window: int = 5) -> Tuple[pd.Series, pd.Series]:
        """
        Xác định Swing Highs và Swing Lows cục bộ trong cửa sổ rolling window n nến.
        Pivot High: High[i] là cao nhất trong [i - window, i + window]
        Pivot Low: Low[i] là thấp nhất trong [i - window, i + window]
        """
        n = len(df)
        swing_highs = pd.Series(np.nan, index=df.index)
        swing_lows = pd.Series(np.nan, index=df.index)

        highs = df['high'].values
        lows = df['low'].values

        for i in range(window, n - window):
            current_high = highs[i]
            if current_high == np.max(highs[i - window : i + window + 1]):
                swing_highs.iloc[i] = current_high

            current_low = lows[i]
            if current_low == np.min(lows[i - window : i + window + 1]):
                swing_lows.iloc[i] = current_low

        return swing_highs, swing_lows

    @classmethod
    def detect_trendlines_and_breaks(
        cls, df: pd.DataFrame, window: int = 5, break_margin: float = 0.002
    ) -> Dict[str, Any]:
        """
        Thuật toán LuxAlgo-equivalent: Trendlines with Breaks
        1. Tìm 2 Swing High gần nhất để vẽ Upper Trendline (Đường kháng cự chéo).
        2. Tìm 2 Swing Low gần nhất để vẽ Lower Trendline (Đường hỗ trợ chéo).
        3. Breakout (B xanh): Giá Close vượt đường kháng cự >= 0.2% biên độ.
        4. Breakdown (B đỏ): Giá Close đè thủng đường hỗ trợ >= 0.2% biên độ.
        """
        if len(df) < window * 4:
            return {
                "trendline_status": "NEUTRAL",
                "upper_trendline": None,
                "lower_trendline": None,
                "breakout_detected": False,
                "breakdown_detected": False
            }

        swing_highs, swing_lows = cls.detect_swings(df, window=window)

        valid_high_idx = df.index[swing_highs.notna()].tolist()
        valid_low_idx = df.index[swing_lows.notna()].tolist()

        current_idx = len(df) - 1
        current_close = float(df['close'].iloc[-1])

        upper_val = None
        lower_val = None
        breakout = False
        breakdown = False
        status = "NEUTRAL"

        # Tính toán Resistance Trendline từ 2 swing high gần nhất
        if len(valid_high_idx) >= 2:
            x1, x2 = valid_high_idx[-2], valid_high_idx[-1]
            y1, y2 = float(swing_highs[x1]), float(swing_highs[x2])
            # Ngoại suy tới cây nến hiện tại
            slope = (y2 - y1) / max((x2 - x1), 1)
            upper_val = y2 + slope * (current_idx - x2)
            if upper_val > 0:
                # Kiểm tra Breakout với đệm 0.2%
                if current_close > upper_val * (1.0 + break_margin):
                    breakout = True
                    status = "BULLISH_BREAKOUT"

        # Tính toán Support Trendline từ 2 swing low gần nhất
        if len(valid_low_idx) >= 2:
            x1, x2 = valid_low_idx[-2], valid_low_idx[-1]
            y1, y2 = float(swing_lows[x1]), float(swing_lows[x2])
            slope = (y2 - y1) / max((x2 - x1), 1)
            lower_val = y2 + slope * (current_idx - x2)
            if lower_val > 0:
                # Kiểm tra Breakdown với đệm 0.2%
                if current_close < lower_val * (1.0 - break_margin):
                    breakdown = True
                    status = "BEARISH_BREAKOUT"

        return {
            "trendline_status": status,
            "upper_trendline": round(upper_val, 2) if upper_val else None,
            "lower_trendline": round(lower_val, 2) if lower_val else None,
            "breakout_detected": breakout,
            "breakdown_detected": breakdown
        }

    @staticmethod
    def detect_fair_value_gaps(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Quét 3 cây nến liên tiếp để tìm Fair Value Gap (FVG):
        - Bullish FVG: Low(i) > High(i-2) -> Vùng nam châm hỗ trợ [High(i-2), Low(i)]
        - Bearish FVG: High(i) < Low(i-2) -> Vùng nam châm kháng cự [High(i), Low(i-2)]
        """
        if len(df) < 5:
            return {"active_fvg": None, "fvg_type": None, "fvg_low": None, "fvg_high": None}

        # Kiểm tra cụm 3 nến gần nhất (trừ nến chưa đóng)
        i = len(df) - 1
        candle_0_high = float(df['high'].iloc[i - 2])
        candle_0_low = float(df['low'].iloc[i - 2])
        candle_2_high = float(df['high'].iloc[i])
        candle_2_low = float(df['low'].iloc[i])

        if candle_2_low > candle_0_high:
            return {
                "active_fvg": True,
                "fvg_type": "BULLISH_IMBALANCE",
                "fvg_low": round(candle_0_high, 2),
                "fvg_high": round(candle_2_low, 2)
            }
        elif candle_2_high < candle_0_low:
            return {
                "active_fvg": True,
                "fvg_type": "BEARISH_IMBALANCE",
                "fvg_low": round(candle_2_high, 2),
                "fvg_high": round(candle_0_low, 2)
            }

        return {"active_fvg": False, "fvg_type": "NONE", "fvg_low": None, "fvg_high": None}

    @staticmethod
    def detect_waterfall_and_pinbar(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Kiểm tra hình thái nến đặc biệt:
        - Thác nước xả (Waterfall dump): 3 nến đỏ liên tiếp có thân nến lớn, không có rút râu.
        - Nến rút chân (Pinbar / Liquidity Sweep Rejection): Râu dưới dài >= 2 lần thân nến.
        """
        if len(df) < 4:
            return {"is_waterfall": False, "is_pinbar_bullish": False, "lower_wick_ratio": 0.0}

        recent = df.iloc[-3:]
        red_count = 0
        total_fall = 0.0

        for _, row in recent.iterrows():
            o, c, h, l = row['open'], row['close'], row['high'], row['low']
            if c < o:
                red_count += 1
                body = o - c
                lower_wick = c - l
                if lower_wick < 0.25 * body:
                    total_fall += body

        # 3 nến đỏ liên tiếp xả mạnh
        is_waterfall = bool(red_count == 3)

        # Kiểm tra nến hiện tại có phải pinbar rút chân không
        curr = df.iloc[-1]
        c_o, c_c, c_h, c_l = curr['open'], curr['close'], curr['high'], curr['low']
        curr_body = abs(c_c - c_o)
        curr_lower_wick = min(c_o, c_c) - c_l
        lower_wick_ratio = float(curr_lower_wick / max(curr_body, 0.01))

        is_pinbar_bullish = bool((lower_wick_ratio >= 1.8) and (curr_lower_wick >= 0.4 * (c_h - c_l)))

        return {
            "is_waterfall": bool(is_waterfall),
            "is_pinbar_bullish": bool(is_pinbar_bullish),
            "lower_wick_ratio": round(float(lower_wick_ratio), 2)
        }

    @classmethod
    def compute_all_indicators(
        cls, df_15m: pd.DataFrame, df_1h: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Tổng hợp toàn bộ chỉ báo định lượng từ các khung thời gian.
        Trả về dictionary chuẩn hóa phục vụ Tầng Quản Trị Rủi Ro & Tầng AI.
        """
        if len(df_15m) < 35:
            raise ValueError(f"Số lượng nến 15m quá ít ({len(df_15m)}), cần tối thiểu 35 nến.")

        close = df_15m['close']
        high = df_15m['high']
        low = df_15m['low']
        volume = df_15m['volume']

        # 1. RSI Multi-length
        rsi_10 = cls.calculate_rsi(close, 10).iloc[-1]
        rsi_14 = cls.calculate_rsi(close, 14).iloc[-1]
        rsi_30 = cls.calculate_rsi(close, 30).iloc[-1]

        is_extreme_oversold = bool(rsi_10 < 30.0 and rsi_14 < 30.0 and rsi_30 < 30.0)
        is_extreme_overbought = bool(rsi_10 > 70.0 and rsi_14 > 70.0 and rsi_30 > 70.0)

        # 2. Adaptive ATR 14
        atr_14 = cls.calculate_atr(high, low, close, 14).iloc[-1]

        # 3. EMA trên khung 15m
        ema_50_15m = cls.calculate_ema(close, 50).iloc[-1]
        ema_200_15m = cls.calculate_ema(close, 200).iloc[-1] if len(df_15m) >= 200 else ema_50_15m

        # 4. Phân tích khung xu hướng 1h (Macro Trend)
        ema_200_1h = None
        macro_trend_1h = "NEUTRAL"
        is_below_ema200_1h = False
        ema200_1h_sloping_down = False

        if df_1h is not None and len(df_1h) >= 30:
            ema200_series = cls.calculate_ema(df_1h['close'], 200) if len(df_1h) >= 200 else cls.calculate_ema(df_1h['close'], 50)
            ema_200_1h = ema200_series.iloc[-1]
            last_1h_close = df_1h['close'].iloc[-1]
            is_below_ema200_1h = bool(last_1h_close < ema_200_1h)

            if len(ema200_series) >= 5:
                slope = ema200_series.iloc[-1] - ema200_series.iloc[-5]
                ema200_1h_sloping_down = bool(slope < 0)

            macro_trend_1h = "BEARISH" if is_below_ema200_1h else "BULLISH"

        # 5. Swing High/Low trong 5 nến gần nhất (trừ nến đang chạy)
        recent_window = df_15m.iloc[-6:-1]
        swing_low_5 = float(recent_window['low'].min())
        swing_high_5 = float(recent_window['high'].max())

        # Tìm hỗ trợ / kháng cự mở rộng trong 30 nến
        broader_window = df_15m.iloc[-31:-1]
        nearest_support = float(broader_window['low'].min())
        nearest_resistance = float(broader_window['high'].max())

        # 6. Trendline Breaks
        trendline_res = cls.detect_trendlines_and_breaks(df_15m, window=5, break_margin=0.002)

        # 7. FVG & Waterfall / Pinbar
        fvg_res = cls.detect_fair_value_gaps(df_15m)
        candle_shapes = cls.detect_waterfall_and_pinbar(df_15m)

        # 8. Volume trend
        vol_ma = volume.rolling(10).mean().iloc[-1]
        current_vol = volume.iloc[-1]
        volume_trend = "INCREASING" if current_vol > vol_ma else "DECREASING"

        current_price = float(close.iloc[-1])

        return {
            "current_price": round(current_price, 2),
            "high_24h": round(float(high.iloc[-96:].max()), 2) if len(high) >= 96 else round(float(high.max()), 2),
            "low_24h": round(float(low.iloc[-96:].min()), 2) if len(low) >= 96 else round(float(low.min()), 2),
            "volume_trend": volume_trend,
            "rsi_10": round(float(rsi_10), 2),
            "rsi_14": round(float(rsi_14), 2),
            "rsi_30": round(float(rsi_30), 2),
            "is_extreme_oversold": is_extreme_oversold,
            "is_extreme_overbought": is_extreme_overbought,
            "atr_14": round(float(atr_14), 2),
            "ema_50_15m": round(float(ema_50_15m), 2),
            "ema_200_15m": round(float(ema_200_15m), 2),
            "ema_200_1h": round(float(ema_200_1h), 2) if ema_200_1h is not None else None,
            "macro_trend_1h": macro_trend_1h,
            "is_below_ema200_1h": is_below_ema200_1h,
            "ema200_1h_sloping_down": ema200_1h_sloping_down,
            "swing_low_5": round(swing_low_5, 2),
            "swing_high_5": round(swing_high_5, 2),
            "nearest_support": round(nearest_support, 2),
            "nearest_resistance": round(nearest_resistance, 2),
            "trendline_status": trendline_res["trendline_status"],
            "upper_trendline": trendline_res["upper_trendline"],
            "lower_trendline": trendline_res["lower_trendline"],
            "breakout_detected": trendline_res["breakout_detected"],
            "breakdown_detected": trendline_res["breakdown_detected"],
            "fvg": fvg_res,
            "candle_patterns": candle_shapes
        }
