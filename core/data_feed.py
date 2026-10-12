"""
core/data_feed.py
Tier 1: Data Feed Module
Quản lý kết nối Binance Public REST/WS API, Ring Buffer 300 nến đa khung (15m, 1h, 4h),
tự động xử lý Exponential Backoff và Circuit Breaker chống Rate Limit (HTTP 429).
"""

import time
import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import requests

try:
    import ccxt
except ImportError:
    ccxt = None

logger = logging.getLogger("DataFeed")


@dataclass
class Candle:
    timestamp: int       # Milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume
        }


class CandleRingBuffer:
    """Ring Buffer lưu trữ tối đa N nến đóng cửa gần nhất cho 1 khung thời gian"""
    def __init__(self, maxlen: int = 300):
        self.maxlen = maxlen
        self.candles: deque[Candle] = deque(maxlen=maxlen)

    def append(self, candle: Candle):
        self.candles.append(candle)

    def extend(self, candle_list: List[Candle]):
        for c in candle_list:
            self.candles.append(c)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.candles:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        data = [c.to_dict() for c in self.candles]
        df = pd.DataFrame(data)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    def __len__(self):
        return len(self.candles)


class MarketDataFeed:
    """
    Market Data Feed chịu trách nhiệm kéo dữ liệu OHLCV từ Binance Public Endpoints.
    Tích hợp Circuit Breaker và Exponential Backoff.
    """
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        ring_buffer_size: int = 300,
        use_futures: bool = True
    ):
        self.symbols = symbols or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        self.ring_buffer_size = ring_buffer_size
        self.use_futures = use_futures

        # Buffers: { symbol: { "15m": CandleRingBuffer, "1h": CandleRingBuffer, "4h": CandleRingBuffer } }
        self.buffers: Dict[str, Dict[str, CandleRingBuffer]] = {
            s: {
                "15m": CandleRingBuffer(maxlen=ring_buffer_size),
                "1h": CandleRingBuffer(maxlen=ring_buffer_size),
                "4h": CandleRingBuffer(maxlen=ring_buffer_size),
            }
            for s in self.symbols
        }

        # Circuit Breaker state
        self.circuit_broken: bool = False
        self.consecutive_errors: int = 0
        self.circuit_break_until: float = 0.0
        self.max_consecutive_errors: int = 3
        self.circuit_break_duration: float = 60.0  # 60s freeze on 429 / persistent errors

        # Initialize CCXT if available
        self.exchange = None
        if ccxt:
            try:
                exchange_class = ccxt.binance
                self.exchange = exchange_class({
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'future' if use_futures else 'spot'
                    }
                })
            except Exception as e:
                logger.warning(f"Không thể khởi tạo ccxt.binance: {e}. Sẽ dùng Direct Binance REST API.")

    def _check_circuit_breaker(self) -> bool:
        """Kiểm tra xem Circuit Breaker có đang khóa không"""
        if self.circuit_broken:
            now = time.time()
            if now < self.circuit_break_until:
                remaining = int(self.circuit_break_until - now)
                logger.warning(f"Circuit Breaker đang KÍCH HOẠT. Tạm dừng kết nối sàn ({remaining}s còn lại).")
                return False
            else:
                logger.info("Circuit Breaker giải phóng. Bắt đầu thử kết nối lại...")
                self.circuit_broken = False
                self.consecutive_errors = 0
        return True

    def _trigger_circuit_breaker(self):
        """Kích hoạt Circuit Breaker khi gặp quá nhiều lỗi liên tiếp hoặc HTTP 429"""
        self.circuit_broken = True
        self.circuit_break_until = time.time() + self.circuit_break_duration
        logger.error(f"KÍCH HOẠT CIRCUIT BREAKER! Tạm dừng request tới Binance trong {self.circuit_break_duration}s.")

    def _parse_binance_klines(self, data: list) -> List[Candle]:
        candles = []
        for row in data:
            candles.append(Candle(
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5])
            ))
        return candles

    def _parse_bybit_klines(self, raw_list: list) -> List[Candle]:
        candles = []
        # Bybit trả về từ nến mới nhất tới cũ nhất -> Đảo ngược lại theo thứ tự thời gian tăng dần
        for row in reversed(raw_list):
            candles.append(Candle(
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5])
            ))
        return candles

    def fetch_ohlcv_direct(self, symbol: str, timeframe: str, limit: int = 100) -> List[Candle]:
        """
        Kéo nến đa kênh với cơ chế tự động chuyển vùng khi bị Cloud WAF chặn (HTTP 418 Teapot):
        1. data-api.binance.vision (Binance official mirror không chặn Cloudflare IP)
        2. api.bybit.com (Bybit linear perpetual klines - Không bị chặn trên Render/AWS)
        3. api.binance.com (Binance Spot)
        4. fapi.binance.com (Binance Futures)
        """
        clean_symbol = symbol.replace("/", "").replace(":USDT", "").upper()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # 1. Thử Binance Vision Public Data Mirror (Khắc phục triệt để lỗi 418 trên Render)
        try:
            url = "https://data-api.binance.vision/api/v3/klines"
            params = {"symbol": clean_symbol, "interval": timeframe, "limit": limit}
            resp = requests.get(url, params=params, headers=headers, timeout=4.0)
            if resp.status_code == 200:
                return self._parse_binance_klines(resp.json())
        except Exception as e:
            logger.debug(f"data-api.binance.vision lỗi: {e}")

        # 2. Thử Bybit Public API (Hỗ trợ 100% cloud hostings, không chặn IP server)
        try:
            bybit_tf_map = {"15m": "15", "1h": "60", "4h": "240", "1d": "D"}
            bybit_tf = bybit_tf_map.get(timeframe, "15")
            bybit_url = "https://api.bybit.com/v5/market/kline"
            bybit_params = {"category": "linear", "symbol": clean_symbol, "interval": bybit_tf, "limit": limit}
            resp = requests.get(bybit_url, params=bybit_params, headers=headers, timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retCode") == 0 and "list" in data.get("result", {}):
                    return self._parse_bybit_klines(data["result"]["list"])
        except Exception as e:
            logger.debug(f"api.bybit.com lỗi: {e}")

        # 3. Thử Binance Spot Public API
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": clean_symbol, "interval": timeframe, "limit": limit}
            resp = requests.get(url, params=params, headers=headers, timeout=4.0)
            if resp.status_code == 200:
                return self._parse_binance_klines(resp.json())
        except Exception as e:
            logger.debug(f"api.binance.com lỗi: {e}")

        # 4. Thử Binance Futures (nếu không dính WAF Teapot)
        try:
            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {"symbol": clean_symbol, "interval": timeframe, "limit": limit}
            resp = requests.get(url, params=params, headers=headers, timeout=4.0)
            if resp.status_code == 200:
                return self._parse_binance_klines(resp.json())
        except Exception as e:
            logger.debug(f"fapi.binance.com lỗi: {e}")

        raise RuntimeError(f"Tất cả các nguồn dữ liệu công khai (Binance Vision, Bybit, Binance Spot) đều không phản hồi cho {symbol}")

    def fetch_candles_with_backoff(
        self, symbol: str, timeframe: str, limit: int = 100, max_retries: int = 3
    ) -> List[Candle]:
        """
        Kéo nến với thuật toán Exponential Backoff và bảo vệ Circuit Breaker
        """
        if not self._check_circuit_breaker():
            return []

        delay = 1.0  # Initial delay
        for attempt in range(max_retries):
            try:
                # 1. Thử dùng CCXT nếu khả dụng
                if self.exchange:
                    try:
                        raw_data = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                        candles = [
                            Candle(
                                timestamp=int(row[0]),
                                open=float(row[1]),
                                high=float(row[2]),
                                low=float(row[3]),
                                close=float(row[4]),
                                volume=float(row[5])
                            )
                            for row in raw_data
                        ]
                        self.consecutive_errors = 0
                        return candles
                    except Exception as ccxt_err:
                        logger.debug(f"CCXT fetch lỗi, chuyển sang Direct Multi-Tier Endpoints: {ccxt_err}")

                # 2. Gọi qua Direct Multi-Tier Endpoints (Binance Vision / Bybit / Spot)
                candles = self.fetch_ohlcv_direct(symbol, timeframe, limit=limit)
                self.consecutive_errors = 0
                return candles

            except Exception as e:
                self.consecutive_errors += 1
                logger.warning(
                    f"Lỗi kéo nến {symbol} {timeframe} (Lần thử {attempt + 1}/{max_retries}): {e}"
                )
                if self.consecutive_errors >= self.max_consecutive_errors:
                    self._trigger_circuit_breaker()
                    return []
                time.sleep(delay)
                delay *= 2.0  # Exponential backoff

        return []

    def sync_buffers(self, symbols: Optional[List[str]] = None, timeframes: Optional[List[str]] = None) -> bool:
        """
        Đồng bộ dữ liệu nến cho tất cả các symbol và khung thời gian được cấu hình.
        """
        target_symbols = symbols or self.symbols
        target_tfs = timeframes or ["15m", "1h", "4h"]
        success = True

        for sym in target_symbols:
            if sym not in self.buffers:
                self.buffers[sym] = {tf: CandleRingBuffer(maxlen=self.ring_buffer_size) for tf in target_tfs}

            for tf in target_tfs:
                candles = self.fetch_candles_with_backoff(sym, tf, limit=min(self.ring_buffer_size, 300))
                if candles:
                    self.buffers[sym][tf].candles.clear()
                    self.buffers[sym][tf].extend(candles)
                else:
                    success = False
        return success

    def get_dataframe(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Lấy DataFrame nến đã chuẩn bị sẵn từ Ring Buffer"""
        if symbol in self.buffers and timeframe in self.buffers[symbol]:
            return self.buffers[symbol][timeframe].to_dataframe()
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Lấy giá hiện tại từ nến đóng cửa mới nhất của khung 15m"""
        df = self.get_dataframe(symbol, "15m")
        if not df.empty:
            return float(df["close"].iloc[-1])
        return None
