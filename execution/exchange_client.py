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

    def test_connection(self) -> Dict[str, Any]:
        """Kiểm tra tính hợp lệ của API Key và lấy số dư tài khoản Futures (tự động thử các endpoint Demo/Testnet)"""
        if not self.api_key or not self.api_secret:
            return {"success": False, "message": "Chưa cung cấp API Key hoặc Secret."}

        last_error = ""
        for url in self.candidate_urls:
            endpoint = f"{url}/fapi/v2/balance"
            try:
                signed_query = self._sign_params({})
                resp = self.session.get(f"{endpoint}?{signed_query}", timeout=8.0)
                if resp.status_code == 200:
                    self.base_url = url
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
                else:
                    err = resp.json() if resp.headers.get("content-type") == "application/json" else resp.text
                    last_error = f"(HTTP {resp.status_code}): {err}"
            except Exception as e:
                last_error = str(e)

        return {
            "success": False,
            "exchange": "binance",
            "message": f"Lỗi Binance {last_error}"
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
        Đặt lệnh Limit Order lên Binance Futures kèm Stop Loss & Take Profit tự động.
        """
        # Chuẩn hóa symbol: "BTC/USDT" -> "BTCUSDT"
        clean_symbol = symbol.replace("/", "").upper()
        norm_side = "BUY" if "BUY" in side.upper() else "SELL"
        opp_side = "SELL" if norm_side == "BUY" else "BUY"

        # 1. Đặt Lệnh Chính (Main Entry Order)
        params = {
            "symbol": clean_symbol,
            "side": norm_side,
            "type": "LIMIT" if order_type.upper() == "LIMIT" else "MARKET",
            "quantity": quantity
        }
        if order_type.upper() == "LIMIT":
            params["price"] = price
            params["timeInForce"] = "GTC"

        try:
            resp = None
            data = None
            for candidate in self.candidate_urls:
                order_url = f"{candidate}/fapi/v1/order"
                signed_query = self._sign_params(params)
                resp = self.session.post(f"{order_url}?{signed_query}", timeout=8.0)
                data = resp.json()
                if resp.status_code == 200:
                    self.base_url = candidate
                    break

            if not resp or resp.status_code != 200:
                logger.error(f"Binance đặt lệnh chính thất bại: {data}")
                return {
                    "success": False,
                    "exchange": "binance",
                    "error": data.get("msg", str(data)) if isinstance(data, dict) else str(data),
                    "raw": data
                }

            order_id = str(data.get("orderId"))
            client_oid = str(data.get("clientOrderId"))
            sl_order_id = None
            tp_order_id = None

            # 2. Đặt Lệnh Stop Loss (STOP_MARKET)
            if stop_loss and stop_loss > 0:
                try:
                    sl_params = {
                        "symbol": clean_symbol,
                        "side": opp_side,
                        "type": "STOP_MARKET",
                        "stopPrice": stop_loss,
                        "closePosition": "true"
                    }
                    sl_query = self._sign_params(sl_params)
                    sl_resp = self.session.post(f"{order_url}?{sl_query}", timeout=6.0)
                    if sl_resp.status_code == 200:
                        sl_order_id = str(sl_resp.json().get("orderId"))
                        logger.info(f"Đã gắn Stop Loss {stop_loss} cho {clean_symbol} (Order #{sl_order_id})")
                except Exception as sl_err:
                    logger.warning(f"Lỗi khi gắn SL: {sl_err}")

            # 3. Đặt Lệnh Take Profit (TAKE_PROFIT_MARKET)
            if take_profit and take_profit > 0:
                try:
                    tp_params = {
                        "symbol": clean_symbol,
                        "side": opp_side,
                        "type": "TAKE_PROFIT_MARKET",
                        "stopPrice": take_profit,
                        "closePosition": "true"
                    }
                    tp_query = self._sign_params(tp_params)
                    tp_resp = self.session.post(f"{order_url}?{tp_query}", timeout=6.0)
                    if tp_resp.status_code == 200:
                        tp_order_id = str(tp_resp.json().get("orderId"))
                        logger.info(f"Đã gắn Take Profit {take_profit} cho {clean_symbol} (Order #{tp_order_id})")
                except Exception as tp_err:
                    logger.warning(f"Lỗi khi gắn TP: {tp_err}")

            return {
                "success": True,
                "exchange": "binance",
                "is_testnet": self.is_testnet,
                "order_id": order_id,
                "client_order_id": client_oid,
                "sl_order_id": sl_order_id,
                "tp_order_id": tp_order_id,
                "status": data.get("status", "NEW"),
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
