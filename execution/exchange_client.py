"""
execution/exchange_client.py
Cổng kết nối Sàn Giao Dịch & Quản Lý Đặt Lệnh (Exchange Client Connector)
Hỗ trợ:
1. Binance USDT-M Futures (Testnet & Mainnet)
2. Bybit USDT Perpetual (Testnet & Mainnet V5 API)
3. Webhook Alert Bridge (TradingView / External Bots)
Xác thực chuẩn mật mã học HMAC-SHA256, không phụ thuộc thư viện ngoài phức tạp.
"""

import time
import hmac
import hashlib
import json
import logging
import urllib.parse
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("ExchangeClient")


def format_symbol_price(symbol: str, price: float) -> float:
    """Format giá theo đúng tick size của từng cặp coin Futures"""
    clean = symbol.replace("/", "").upper()
    if "BTC" in clean:
        # Binance BTCUSDT tickSize = 0.10 -> tối đa 1 số thập phân
        return round(float(price), 1)
    elif "ETH" in clean:
        # ETHUSDT tickSize = 0.01 -> tối đa 2 số thập phân
        return round(float(price), 2)
    elif "SOL" in clean:
        # SOLUSDT tickSize = 0.01 -> tối đa 2 số thập phân
        return round(float(price), 2)
    return round(float(price), 2)


def format_symbol_quantity(symbol: str, quantity: float) -> float:
    """Format khối lượng theo step size hợp lệ của từng coin Futures"""
    clean = symbol.replace("/", "").upper()
    if "BTC" in clean or "ETH" in clean:
        return round(float(quantity), 3)
    elif "SOL" in clean:
        return round(float(quantity), 2)
    return round(float(quantity), 3)


class BaseExchangeClient:
    """Interface cơ sở cho các kết nối sàn giao dịch"""
    def test_connection(self) -> Dict[str, Any]:
        raise NotImplementedError

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def get_open_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin vị thế đang mở trên sàn (nếu có)"""
        return None

    def has_open_orders(self, symbol: str) -> bool:
        """Kiểm tra xem trên sàn có lệnh chờ đang mở không"""
        return False

    def get_open_orders(self, symbol: str) -> list:
        """Lấy danh sách chi tiết các lệnh chờ đang mở trên sàn"""
        return []

    def cancel_conditional_orders(self, symbol: str) -> int:
        """Hủy các lệnh điều kiện (STOP_MARKET, TAKE_PROFIT_MARKET) đang chờ"""
        return 0

    def attach_position_tpsl(
        self,
        symbol: str,
        side: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        position_side: Optional[str] = None
    ) -> Dict[str, Any]:
        """Gắn trực tiếp TP và SL vào vị thế đang mở trên sàn"""
        return {"success": False, "message": "Not implemented"}


class BinanceFuturesClient(BaseExchangeClient):
    """
    Client giao tiếp Binance USDT-M Futures API (REST v1 & v2).
    Hỗ trợ Testnet: https://testnet.binancefuture.com
    Hỗ trợ Mainnet: https://fapi.binance.com
    """
    def __init__(self, api_key: str, api_secret: str, is_testnet: bool = True):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.is_testnet = is_testnet
        # Hỗ trợ cả Binance Demo Trading (demo-fapi.binance.com) và Testnet truyền thống (testnet.binancefuture.com)
        self.candidate_urls = (
            ["https://demo-fapi.binance.com", "https://testnet.binancefuture.com"]
            if is_testnet
            else ["https://fapi.binance.com"]
        )
        self.base_url = self.candidate_urls[0]
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "AI-Trading-Copilot/1.0 (Python/Windows)"
        })

    def _sign_params(self, params: Dict[str, Any]) -> str:
        """Ký các tham số request theo chuẩn HMAC-SHA256 của Binance"""
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return f"{query_string}&signature={signature}"

    def _signed_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 8.0
    ) -> Optional[requests.Response]:
        """
        Gửi HTTP request có ký số HMAC-SHA256.
        Tự động fallback giữa các candidate_urls (Demo Trading và Legacy Testnet).
        Cập nhật self.base_url khi tìm thấy endpoint phản hồi hợp lệ.
        """
        if params is None:
            params = {}

        last_resp = None
        urls = [self.base_url] + [u for u in self.candidate_urls if u != self.base_url]
        for base in urls:
            signed_q = self._sign_params(params.copy())
            url = f"{base}{path}"
            try:
                if method.upper() == "GET":
                    resp = self.session.get(f"{url}?{signed_q}", timeout=timeout)
                elif method.upper() == "POST":
                    resp = self.session.post(f"{url}?{signed_q}", timeout=timeout)
                elif method.upper() == "DELETE":
                    resp = self.session.delete(f"{url}?{signed_q}", timeout=timeout)
                else:
                    raise ValueError(f"Phương thức không hỗ trợ: {method}")

                # Nếu domain đúng (không trả về 401 Unauthorized do sai miền API key), lưu lại base_url
                if resp.status_code not in (401, 403, 404, 502, 503):
                    self.base_url = base
                    return resp
                last_resp = resp
            except Exception as e:
                logger.debug(f"Request tới {base}{path} gặp sự cố: {e}")
                continue
        return last_resp

    def test_connection(self) -> Dict[str, Any]:
        """Kiểm tra tính hợp lệ của API Key và lấy số dư tài khoản Futures (tự động thử các endpoint Demo/Testnet)"""
        if not self.api_key or not self.api_secret:
            return {"success": False, "message": "Chưa cung cấp API Key hoặc Secret."}

        resp = self._signed_request("GET", "/fapi/v2/balance")
        if resp and resp.status_code == 200:
            balances = resp.json()
            usdt_bal = next((b for b in balances if b.get("asset") == "USDT"), None)
            available = float(usdt_bal.get("availableBalance", 0.0)) if usdt_bal else 0.0
            env_tag = "Demo/Testnet" if self.is_testnet else "Mainnet"
            return {
                "success": True,
                "exchange": "binance",
                "is_testnet": self.is_testnet,
                "base_url": self.base_url,
                "available_balance": available,
                "message": f"Kết nối Binance Futures ({env_tag}) thành công! Số dư khả dụng: ${available:,.2f} USDT"
            }

        last_error = f"(HTTP {resp.status_code}): {resp.text}" if resp else "Không thể kết nối sàn."
        return {
            "success": False,
            "exchange": "binance",
            "message": f"Lỗi Binance {last_error}"
        }

    def get_open_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin vị thế đang mở (nếu có) trên Binance Futures"""
        clean_symbol = symbol.replace("/", "").upper()
        resp = self._signed_request("GET", "/fapi/v2/positionRisk", {"symbol": clean_symbol})
        if resp and resp.status_code == 200:
            positions = resp.json()
            for p in positions:
                if p.get("symbol") == clean_symbol:
                    amt = float(p.get("positionAmt", 0.0))
                    if abs(amt) > 0:
                        return {
                            "symbol": symbol,
                            "clean_symbol": clean_symbol,
                            "size": abs(amt),
                            "side": "LONG" if amt > 0 else "SHORT",
                            "position_side": p.get("positionSide", "BOTH"),
                            "entry_price": float(p.get("entryPrice", 0.0)),
                            "mark_price": float(p.get("markPrice", 0.0)),
                            "unrealized_pnl": float(p.get("unRealizedProfit", 0.0))
                        }
        return None

    def has_open_orders(self, symbol: str) -> bool:
        """Kiểm tra xem trên sàn có lệnh chờ (Pending Limit / Stop order) cho cặp coin này không"""
        orders = self.get_open_orders(symbol)
        return len(orders) > 0

    def get_open_orders(self, symbol: str) -> list:
        """Lấy danh sách các lệnh đang chờ (Open Orders) của symbol"""
        clean_symbol = symbol.replace("/", "").upper()
        resp = self._signed_request("GET", "/fapi/v1/openOrders", {"symbol": clean_symbol})
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
        return []

    def cancel_conditional_orders(self, symbol: str) -> int:
        """Hủy các lệnh STOP_MARKET và TAKE_PROFIT_MARKET cũ để chống xung đột lệnh"""
        clean_symbol = symbol.replace("/", "").upper()
        orders = self.get_open_orders(symbol)
        if not isinstance(orders, list):
            return 0
        cancelled = 0
        for o in orders:
            if isinstance(o, dict) and o.get("type") in ("STOP_MARKET", "STOP", "TAKE_PROFIT_MARKET", "TAKE_PROFIT"):
                oid = o.get("orderId")
                try:
                    self._signed_request("DELETE", "/fapi/v1/order", {"symbol": clean_symbol, "orderId": oid})
                    cancelled += 1
                except Exception:
                    pass
        return cancelled

    def attach_position_tpsl(
        self,
        symbol: str,
        side: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        position_side: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Gắn Stop Loss và Take Profit trực tiếp vào vị thế đang mở trên Binance Futures.
        Sử dụng closePosition='true' và workingType='MARK_PRICE' để kích hoạt cột 'TP/SL for position'.
        """
        clean_symbol = symbol.replace("/", "").upper()
        is_long = side.upper() in ("LONG", "BUY")
        opp_side = "SELL" if is_long else "BUY"

        # Tự động lấy mark_price hiện tại để phòng vệ lỗi -2021 (Order would immediately trigger)
        pos = self.get_open_position(symbol)
        mark_price = pos.get("mark_price", 0.0) if pos else 0.0
        if not position_side and pos:
            position_side = pos.get("position_side", "BOTH")

        # Hủy các lệnh điều kiện cũ trước khi gắn cặp mới
        self.cancel_conditional_orders(symbol)

        sl_order_id = None
        tp_order_id = None
        errors = []

        # 1. Gắn Stop Loss (STOP_MARKET)
        if stop_loss and stop_loss > 0:
            valid_sl = float(stop_loss)
            if mark_price > 0:
                if is_long and valid_sl >= mark_price:
                    valid_sl = mark_price * 0.995  # Buộc SL phải thấp hơn Mark Price nếu là Long
                elif not is_long and valid_sl <= mark_price:
                    valid_sl = mark_price * 1.005  # Buộc SL phải cao hơn Mark Price nếu là Short

            formatted_sl = format_symbol_price(clean_symbol, valid_sl)
            sl_params: Dict[str, Any] = {
                "symbol": clean_symbol,
                "side": opp_side,
                "type": "STOP_MARKET",
                "stopPrice": formatted_sl,
                "closePosition": "true",
                "workingType": "MARK_PRICE"
            }
            if position_side and position_side.upper() in ("LONG", "SHORT"):
                sl_params["positionSide"] = position_side.upper()

            resp = self._signed_request("POST", "/fapi/v1/order", sl_params)
            if resp and resp.status_code == 200:
                data = resp.json()
                sl_order_id = str(data.get("orderId"))
                logger.info(f"✅ [BINANCE] Đã gắn Stop Loss {formatted_sl} vào vị thế {clean_symbol} (Order #{sl_order_id})")
            else:
                err_data = resp.json() if resp and resp.headers.get("content-type") == "application/json" else (resp.text if resp else "Timeout")
                errors.append(f"SL error: {err_data}")
                logger.warning(f"⚠️ [BINANCE] Không thể gắn SL cho vị thế {clean_symbol}: {err_data}")

        # 2. Gắn Take Profit (TAKE_PROFIT_MARKET)
        if take_profit and take_profit > 0:
            valid_tp = float(take_profit)
            if mark_price > 0:
                if is_long and valid_tp <= mark_price:
                    valid_tp = mark_price * 1.01   # Buộc TP phải cao hơn Mark Price nếu là Long
                elif not is_long and valid_tp >= mark_price:
                    valid_tp = mark_price * 0.99   # Buộc TP phải thấp hơn Mark Price nếu là Short

            formatted_tp = format_symbol_price(clean_symbol, valid_tp)
            tp_params: Dict[str, Any] = {
                "symbol": clean_symbol,
                "side": opp_side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": formatted_tp,
                "closePosition": "true",
                "workingType": "MARK_PRICE"
            }
            if position_side and position_side.upper() in ("LONG", "SHORT"):
                tp_params["positionSide"] = position_side.upper()

            resp = self._signed_request("POST", "/fapi/v1/order", tp_params)
            if resp and resp.status_code == 200:
                data = resp.json()
                tp_order_id = str(data.get("orderId"))
                logger.info(f"✅ [BINANCE] Đã gắn Take Profit {formatted_tp} vào vị thế {clean_symbol} (Order #{tp_order_id})")
            else:
                err_data = resp.json() if resp and resp.headers.get("content-type") == "application/json" else (resp.text if resp else "Timeout")
                errors.append(f"TP error: {err_data}")
                logger.warning(f"⚠️ [BINANCE] Không thể gắn TP cho vị thế {clean_symbol}: {err_data}")

        return {
            "success": bool(sl_order_id or tp_order_id),
            "sl_order_id": sl_order_id,
            "tp_order_id": tp_order_id,
            "errors": errors
        }

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Đặt lệnh lên Binance Futures kèm Stop Loss & Take Profit tự động.
        Định dạng chính xác tick size và step size để chống lỗi -1111 Precision.
        """
        clean_symbol = symbol.replace("/", "").upper()
        norm_side = "BUY" if "BUY" in side.upper() else "SELL"

        f_price = format_symbol_price(clean_symbol, price)
        f_qty = format_symbol_quantity(clean_symbol, quantity)
        f_sl = format_symbol_price(clean_symbol, stop_loss) if stop_loss else None
        f_tp = format_symbol_price(clean_symbol, take_profit) if take_profit else None

        # 1. Đặt Lệnh Chính (Main Entry Order)
        params: Dict[str, Any] = {
            "symbol": clean_symbol,
            "side": norm_side,
            "type": "LIMIT" if order_type.upper() == "LIMIT" else "MARKET",
            "quantity": f_qty
        }
        if order_type.upper() == "LIMIT":
            params["price"] = f_price
            params["timeInForce"] = "GTC"

        try:
            resp = self._signed_request("POST", "/fapi/v1/order", params)
            if not resp or resp.status_code != 200:
                err_data = resp.json() if resp and resp.headers.get("content-type") == "application/json" else (resp.text if resp else "Timeout")
                logger.error(f"Binance đặt lệnh chính thất bại: {err_data}")
                return {
                    "success": False,
                    "exchange": "binance",
                    "error": err_data.get("msg", str(err_data)) if isinstance(err_data, dict) else str(err_data),
                    "raw": err_data
                }

            data = resp.json()
            order_id = str(data.get("orderId"))
            client_oid = str(data.get("clientOrderId"))
            order_status = data.get("status", "NEW")
            sl_order_id = None
            tp_order_id = None

            # 2. Nếu đã có vị thế mở trên sàn (ví dụ lệnh Market hoặc Limit khớp ngay), gắn Position TP/SL lập tức
            pos = self.get_open_position(symbol)
            if pos and pos.get("size", 0.0) > 0:
                tpsl_res = self.attach_position_tpsl(
                    symbol=symbol,
                    side=pos.get("side", norm_side),
                    stop_loss=f_sl,
                    take_profit=f_tp,
                    position_side=pos.get("position_side")
                )
                sl_order_id = tpsl_res.get("sl_order_id")
                tp_order_id = tpsl_res.get("tp_order_id")

            return {
                "success": True,
                "exchange": "binance",
                "is_testnet": self.is_testnet,
                "order_id": order_id,
                "client_order_id": client_oid,
                "sl_order_id": sl_order_id,
                "tp_order_id": tp_order_id,
                "status": order_status,
                "raw": data
            }

        except Exception as e:
            logger.error(f"Lỗi thực thi lệnh Binance: {e}")
            return {"success": False, "exchange": "binance", "error": str(e)}


class BybitPerpetualClient(BaseExchangeClient):
    """
    Client giao tiếp Bybit V5 Perpetual API.
    Hỗ trợ Testnet: https://api-testnet.bybit.com
    Hỗ trợ Mainnet: https://api.bybit.com
    """
    def __init__(self, api_key: str, api_secret: str, is_testnet: bool = True):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.is_testnet = is_testnet
        self.base_url = "https://api-testnet.bybit.com" if is_testnet else "https://api.bybit.com"
        self.session = requests.Session()

    def _get_headers(self, payload_str: str = "") -> Dict[str, str]:
        """Tạo headers kèm chữ ký theo chuẩn Bybit V5 API"""
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"
        raw_sign = f"{timestamp}{self.api_key}{recv_window}{payload_str}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            raw_sign.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "Content-Type": "application/json"
        }

    def test_connection(self) -> Dict[str, Any]:
        """Kiểm tra API Key và số dư Bybit V5"""
        if not self.api_key or not self.api_secret:
            return {"success": False, "message": "Chưa cung cấp API Key hoặc Secret."}

        url = f"{self.base_url}/v5/account/wallet-balance?accountType=UNIFIED"
        query_str = "accountType=UNIFIED"
        try:
            headers = self._get_headers(query_str)
            resp = self.session.get(url, headers=headers, timeout=8.0)
            data = resp.json()
            if data.get("retCode") == 0:
                coins = data.get("result", {}).get("list", [{}])[0].get("coin", [])
                usdt = next((c for c in coins if c.get("coin") == "USDT"), None)
                bal = float(usdt.get("walletBalance", 0.0)) if usdt else 0.0
                env_tag = "Testnet" if self.is_testnet else "Mainnet"
                return {
                    "success": True,
                    "exchange": "bybit",
                    "is_testnet": self.is_testnet,
                    "available_balance": bal,
                    "message": f"Kết nối Bybit ({env_tag}) thành công! Số dư ví UNIFIED: ${bal:,.2f} USDT"
                }
            else:
                return {
                    "success": False,
                    "exchange": "bybit",
                    "message": f"Bybit trả về lỗi ({data.get('retCode')}): {data.get('retMsg')}"
                }
        except Exception as e:
            return {"success": False, "exchange": "bybit", "message": f"Lỗi kết nối Bybit: {str(e)}"}

    def get_open_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin vị thế đang mở trên Bybit V5"""
        clean_symbol = symbol.replace("/", "").upper()
        url = f"{self.base_url}/v5/position/list?category=linear&symbol={clean_symbol}"
        query_str = f"category=linear&symbol={clean_symbol}"
        try:
            headers = self._get_headers(query_str)
            resp = self.session.get(url, headers=headers, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                positions = data.get("result", {}).get("list", [])
                for p in positions:
                    size = float(p.get("size", 0.0))
                    if size > 0:
                        return {
                            "symbol": symbol,
                            "clean_symbol": clean_symbol,
                            "size": size,
                            "side": "LONG" if p.get("side", "").upper() == "BUY" else "SHORT",
                            "entry_price": float(p.get("avgPrice", 0.0)),
                            "mark_price": float(p.get("markPrice", 0.0)),
                            "unrealized_pnl": float(p.get("unrealisedPnl", 0.0))
                        }
        except Exception as e:
            logger.warning(f"Lỗi kiểm tra vị thế Bybit ({symbol}): {e}")
        return None

    def has_open_orders(self, symbol: str) -> bool:
        """Kiểm tra lệnh chờ trên Bybit V5"""
        return len(self.get_open_orders(symbol)) > 0

    def get_open_orders(self, symbol: str) -> list:
        """Lấy danh sách lệnh chờ trên Bybit V5"""
        clean_symbol = symbol.replace("/", "").upper()
        url = f"{self.base_url}/v5/order/realtime?category=linear&symbol={clean_symbol}"
        query_str = f"category=linear&symbol={clean_symbol}"
        try:
            headers = self._get_headers(query_str)
            resp = self.session.get(url, headers=headers, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", {}).get("list", [])
        except Exception as e:
            logger.warning(f"Lỗi kiểm tra lệnh chờ Bybit ({symbol}): {e}")
        return []

    def attach_position_tpsl(
        self,
        symbol: str,
        side: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        position_side: Optional[str] = None
    ) -> Dict[str, Any]:
        """Gắn TP/SL cho vị thế đang mở trên Bybit V5 qua endpoint /v5/position/trading-stop"""
        clean_symbol = symbol.replace("/", "").upper()
        body: Dict[str, Any] = {
            "category": "linear",
            "symbol": clean_symbol,
            "positionIdx": 0,
            "tpslMode": "Full"
        }
        if stop_loss and stop_loss > 0:
            body["stopLoss"] = str(format_symbol_price(clean_symbol, stop_loss))
        if take_profit and take_profit > 0:
            body["takeProfit"] = str(format_symbol_price(clean_symbol, take_profit))

        payload_str = json.dumps(body)
        url = f"{self.base_url}/v5/position/trading-stop"
        try:
            headers = self._get_headers(payload_str)
            resp = self.session.post(url, data=payload_str, headers=headers, timeout=8.0)
            data = resp.json()
            if data.get("retCode") == 0:
                logger.info(f"✅ [BYBIT] Đã gắn TP/SL cho vị thế {clean_symbol}")
                return {"success": True, "message": "Đã gắn TP/SL trên Bybit"}
            return {"success": False, "errors": [data.get("retMsg", str(data))]}
        except Exception as e:
            return {"success": False, "errors": [str(e)]}

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Bybit V5 cho phép đặt lệnh Limit kèm SL/TP Full Mode trực tiếp trong 1 request duy nhất!
        """
        clean_symbol = symbol.replace("/", "").upper()
        bybit_side = "Buy" if "BUY" in side.upper() else "Sell"

        body: Dict[str, Any] = {
            "category": "linear",
            "symbol": clean_symbol,
            "side": bybit_side,
            "orderType": "Limit" if order_type.upper() == "LIMIT" else "Market",
            "qty": str(quantity),
            "timeInForce": "GTC"
        }
        if order_type.upper() == "LIMIT":
            body["price"] = str(price)

        if stop_loss and stop_loss > 0:
            body["stopLoss"] = str(stop_loss)
            body["tpslMode"] = "Full"

        if take_profit and take_profit > 0:
            body["takeProfit"] = str(take_profit)
            body["tpslMode"] = "Full"

        payload_str = json.dumps(body)
        url = f"{self.base_url}/v5/order/create"
        try:
            headers = self._get_headers(payload_str)
            resp = self.session.post(url, data=payload_str, headers=headers, timeout=8.0)
            data = resp.json()

            if data.get("retCode") == 0:
                res_data = data.get("result", {})
                return {
                    "success": True,
                    "exchange": "bybit",
                    "is_testnet": self.is_testnet,
                    "order_id": res_data.get("orderId"),
                    "client_order_id": res_data.get("orderLinkId"),
                    "sl_order_id": "ATTACHED_TO_ORDER",
                    "tp_order_id": "ATTACHED_TO_ORDER",
                    "status": "Created",
                    "raw": data
                }
            else:
                return {
                    "success": False,
                    "exchange": "bybit",
                    "error": f"Lỗi Bybit ({data.get('retCode')}): {data.get('retMsg')}",
                    "raw": data
                }
        except Exception as e:
            return {"success": False, "exchange": "bybit", "error": str(e)}


class WebhookClient(BaseExchangeClient):
    """
    Bộ chuyển tiếp tín hiệu Webhook (TradingView Alert Bridge / 3Commas / Custom Webhook).
    Gửi JSON payload thông số lệnh tới URL cấu hình.
    """
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url.strip()

    def test_connection(self) -> Dict[str, Any]:
        if not self.webhook_url:
            return {"success": False, "message": "Chưa điền Webhook URL."}
        try:
            resp = requests.post(self.webhook_url, json={"event": "PING", "message": "Test Copilot Webhook"}, timeout=5.0)
            return {
                "success": resp.status_code in (200, 201, 202, 204),
                "exchange": "webhook",
                "message": f"Webhook phản hồi HTTP {resp.status_code}"
            }
        except Exception as e:
            return {"success": False, "exchange": "webhook", "message": f"Lỗi Webhook: {str(e)}"}

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        if not self.webhook_url:
            return {"success": False, "error": "Chưa cấu hình Webhook URL"}

        payload = {
            "event": "ORDER_PROPOSAL",
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "price": price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "timestamp": int(time.time() * 1000)
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=5.0)
            return {
                "success": resp.status_code in (200, 201, 202),
                "exchange": "webhook",
                "order_id": f"WH_{int(time.time())}",
                "status": f"HTTP_{resp.status_code}",
                "raw": resp.text[:200]
            }
        except Exception as e:
            return {"success": False, "exchange": "webhook", "error": str(e)}
