"""
storage/database.py
Tier 5 & Storage: SQLite Database & Trading Journal Logger
Quản lý bảng trade_signals (chuẩn Schema 4.3), active_positions,
tính toán Daily Loss Circuit Breaker, Anti-Tilt Cooldown, Winrate và Profit Factor.
"""

import sqlite3
import json
from datetime import datetime, timezone, date
from typing import Dict, Any, List, Optional, Tuple


class DatabaseManager:
    """
    Quản lý SQLite Database cục bộ cho Hệ Thống Trading Copilot.
    """
    def __init__(self, db_path: str = "storage/trades.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _execute(self, query: str, params: tuple = (), fetch: str = "none"):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch == "one":
                res = cursor.fetchone()
                return dict(res) if res else None
            elif fetch == "all":
                res = cursor.fetchall()
                return [dict(r) for r in res]
            elif fetch == "lastrowid":
                conn.commit()
                return cursor.lastrowid
            conn.commit()
            return None
        finally:
            conn.close()

    def _init_db(self):
        """Khởi tạo schema cơ sở dữ liệu nếu chưa tồn tại"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                position_size REAL NOT NULL,
                risk_amount_usd REAL NOT NULL,
                risk_reward_ratio REAL NOT NULL,
                ai_decision TEXT CHECK(ai_decision IN ('APPROVE', 'REJECT', 'WAIT')),
                ai_confidence REAL,
                ai_reasoning TEXT,
                execution_status TEXT DEFAULT 'PENDING',
                exit_price REAL,
                realized_pnl_usd REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                current_sl REAL NOT NULL,
                original_sl REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                tp3 REAL NOT NULL,
                position_size REAL NOT NULL,
                remaining_size REAL NOT NULL,
                risk_usd REAL NOT NULL,
                is_breakeven INTEGER DEFAULT 0,
                scale_out_phase INTEGER DEFAULT 0,
                open_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'OPEN',
                FOREIGN KEY(signal_id) REFERENCES trade_signals(id)
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                metadata TEXT
            );
            """)

            # 4. Bảng app_settings: Lưu trữ cài đặt người dùng (Vốn, Tỷ lệ rủi ro, API sàn)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 5. Bảng executed_orders: Nhật ký lệnh tự động đã gửi lên sàn
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS executed_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                order_id TEXT,
                client_order_id TEXT,
                status TEXT DEFAULT 'SUBMITTED',
                sl_order_id TEXT,
                tp_order_id TEXT,
                is_testnet INTEGER DEFAULT 1,
                error_message TEXT,
                raw_response TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(signal_id) REFERENCES trade_signals(id)
            );
            """)
            conn.commit()
        finally:
            conn.close()

    def set_setting(self, key: str, value: str):
        """Lưu hoặc cập nhật một tham số cài đặt vào cơ sở dữ liệu"""
        query = """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """
        self._execute(query, (key, str(value)))

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Lấy giá trị cài đặt từ cơ sở dữ liệu"""
        row = self._execute("SELECT value FROM app_settings WHERE key = ?", (key,), fetch="one")
        return row["value"] if row else default

    def set_account_equity(self, equity: float):
        """Lưu vốn tài khoản mới"""
        self.set_setting("account_equity", str(round(float(equity), 2)))

    def get_account_equity(self, default: float = 200.0) -> float:
        """Lấy vốn tài khoản hiện tại"""
        val = self.get_setting("account_equity")
        return float(val) if val is not None else float(default)

    def set_risk_percent(self, percent: float):
        """Lưu tỷ lệ rủi ro mới (%)"""
        self.set_setting("risk_percent", str(round(float(percent), 2)))

    def get_risk_percent(self, default: float = 1.0) -> float:
        """Lấy tỷ lệ rủi ro hiện tại (%)"""
        val = self.get_setting("risk_percent")
        return float(val) if val is not None else float(default)

    # Cấu hình sàn giao dịch & Tự động đặt lệnh (Auto-Trade)
    def save_exchange_config(
        self,
        exchange: str,
        api_key: str,
        api_secret: str,
        is_testnet: bool = True,
        auto_trade_enabled: bool = False,
        webhook_url: Optional[str] = None
    ):
        """Lưu thông tin API Key sàn giao dịch & tùy chọn Auto-Trade"""
        import os
        self.set_setting("exchange_name", exchange.lower().strip())
        self.set_setting("exchange_api_key", api_key.strip())
        if api_secret:  # Chỉ cập nhật nếu có secret mới
            self.set_setting("exchange_api_secret", api_secret.strip())
        self.set_setting("exchange_is_testnet", "1" if is_testnet else "0")
        self.set_setting("auto_trade_enabled", "1" if auto_trade_enabled else "0")
        if webhook_url is not None:
            self.set_setting("exchange_webhook_url", webhook_url.strip())

    def get_exchange_config(self) -> Dict[str, Any]:
        """Lấy cấu hình sàn giao dịch và cờ bật/tắt Auto-Trade"""
        import os
        return {
            "exchange": self.get_setting("exchange_name", os.environ.get("EXCHANGE_NAME", "binance")),
            "api_key": self.get_setting("exchange_api_key", os.environ.get("EXCHANGE_API_KEY", "")),
            "api_secret": self.get_setting("exchange_api_secret", os.environ.get("EXCHANGE_API_SECRET", "")),
            "is_testnet": self.get_setting("exchange_is_testnet", os.environ.get("EXCHANGE_IS_TESTNET", "1")) == "1",
            "auto_trade_enabled": self.get_setting("auto_trade_enabled", os.environ.get("AUTO_TRADE_ENABLED", "0")) == "1",
            "webhook_url": self.get_setting("exchange_webhook_url", os.environ.get("EXCHANGE_WEBHOOK_URL", ""))
        }

    def is_auto_trade_enabled(self) -> bool:
        """Kiểm tra cờ tự động đặt lệnh có đang kích hoạt không"""
        return self.get_setting("auto_trade_enabled", "0") == "1"

    def set_auto_trade_enabled(self, enabled: bool):
        """Bật hoặc tắt tính năng tự động đặt lệnh"""
        self.set_setting("auto_trade_enabled", "1" if enabled else "0")

    def record_executed_order(
        self,
        signal_id: Optional[int],
        exchange: str,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        status: str = "SUBMITTED",
        sl_order_id: Optional[str] = None,
        tp_order_id: Optional[str] = None,
        is_testnet: bool = True,
        error_message: Optional[str] = None,
        raw_response: Optional[Dict[str, Any]] = None
    ) -> int:
        """Lưu bản ghi lệnh tự động vào bảng executed_orders"""
        query = """
        INSERT INTO executed_orders (
            signal_id, exchange, symbol, side, order_type, price, quantity,
            order_id, client_order_id, status, sl_order_id, tp_order_id,
            is_testnet, error_message, raw_response
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        raw_str = json.dumps(raw_response or {}) if isinstance(raw_response, dict) else str(raw_response or "")
        return self._execute(
            query,
            (
                signal_id, exchange, symbol, side, order_type, price, quantity,
                order_id, client_order_id, status, sl_order_id, tp_order_id,
                1 if is_testnet else 0, error_message, raw_str
            ),
            fetch="lastrowid"
        )

    def get_executed_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lấy danh sách các lệnh tự động đã thực thi gần nhất"""
        query = "SELECT * FROM executed_orders ORDER BY id DESC LIMIT ?"
        return self._execute(query, (limit,), fetch="all")

    def has_active_position_or_recent_order(self, symbol: str, cooldown_minutes: int = 15) -> bool:
        """
        Kiểm tra xem cặp coin đã có vị thế đang mở hoặc vừa đặt lệnh gần đây (Idempotency Guard).
        Tránh trường hợp vòng lặp quét 1 phút liên tục kích hoạt gây dồn khối lượng (spamming).
        """
        # 1. Kiểm tra vị thế OPEN trong active_positions
        pos = self._execute(
            "SELECT id FROM active_positions WHERE symbol = ? AND status = 'OPEN'",
            (symbol,),
            fetch="one"
        )
        if pos:
            return True

        # 2. Kiểm tra lệnh vừa được đặt thành công trong vòng cooldown_minutes phút
        recent_order = self._execute(
            """
            SELECT id FROM executed_orders 
            WHERE symbol = ? 
              AND status IN ('SUBMITTED', 'FILLED', 'NEW')
              AND datetime(created_at) >= datetime('now', ?)
            """,
            (symbol, f"-{cooldown_minutes} minutes"),
            fetch="one"
        )
        return bool(recent_order)

    def record_signal(
        self,
        symbol: str,
        timeframe: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        risk_amount_usd: float,
        risk_reward_ratio: float,
        ai_decision: str,
        ai_confidence: float,
        ai_reasoning: str,
        execution_status: str = "PENDING"
    ) -> int:
        """Ghi nhận một tín hiệu giao dịch mới vào bảng trade_signals"""
        query = """
        INSERT INTO trade_signals (
            symbol, timeframe, entry_price, stop_loss, take_profit,
            position_size, risk_amount_usd, risk_reward_ratio,
            ai_decision, ai_confidence, ai_reasoning, execution_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            symbol, timeframe, entry_price, stop_loss, take_profit,
            position_size, risk_amount_usd, risk_reward_ratio,
            ai_decision, ai_confidence, ai_reasoning, execution_status
        )
        return self._execute(query, params, fetch="lastrowid")

    def open_position(
        self,
        signal_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp3: float,
        position_size: float,
        risk_usd: float
    ) -> int:
        """Mở vị thế theo dõi trong hệ thống"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO active_positions (
                signal_id, symbol, side, entry_price, current_sl, original_sl,
                tp1, tp2, tp3, position_size, remaining_size, risk_usd, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """, (
                signal_id, symbol, side, entry_price, stop_loss, stop_loss,
                tp1, tp2, tp3, position_size, position_size, risk_usd
            ))
            pos_id = cursor.lastrowid
            cursor.execute("UPDATE trade_signals SET execution_status = 'EXECUTED' WHERE id = ?", (signal_id,))
            conn.commit()
            return pos_id
        finally:
            conn.close()

    def close_position(self, position_id: int, exit_price: float, realized_pnl: float):
        """Đóng vị thế và cập nhật kết quả lời/lỗ"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT signal_id FROM active_positions WHERE id = ?", (position_id,))
            row = cursor.fetchone()
            signal_id = row["signal_id"] if row else None

            cursor.execute("UPDATE active_positions SET status = 'CLOSED', remaining_size = 0 WHERE id = ?", (position_id,))
            if signal_id:
                cursor.execute("""
                UPDATE trade_signals
                SET execution_status = 'CLOSED', exit_price = ?, realized_pnl_usd = ?
                WHERE id = ?
                """, (exit_price, realized_pnl, signal_id))
            conn.commit()
        finally:
            conn.close()

    def get_active_positions(self) -> List[Dict[str, Any]]:
        """Lấy danh sách các vị thế đang mở (OPEN)"""
        return self._execute("SELECT * FROM active_positions WHERE status = 'OPEN'", fetch="all")

    def get_active_positions_count(self) -> int:
        """Đếm số lượng vị thế đang mở"""
        res = self._execute("SELECT COUNT(*) as cnt FROM active_positions WHERE status = 'OPEN'", fetch="one")
        return res["cnt"] if res else 0

    def update_position_sl_to_breakeven(self, position_id: int, entry_price: float):
        """Đôn Stop Loss về đúng giá Entry (Hòa vốn 0% rủi ro)"""
        self._execute("UPDATE active_positions SET current_sl = ?, is_breakeven = 1 WHERE id = ?", (entry_price, position_id))

    def get_daily_realized_pnl(self) -> float:
        """Tính tổng lãi/lỗ đã thực hiện trong ngày hiện tại (UTC)"""
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        query = """
        SELECT SUM(realized_pnl_usd) as total_pnl
        FROM trade_signals
        WHERE execution_status = 'CLOSED'
          AND DATE(created_at) = DATE(?)
        """
        row = self._execute(query, (today_str,), fetch="one")
        if row and row["total_pnl"] is not None:
            return float(row["total_pnl"])
        return 0.0

    def get_consecutive_losses(self) -> int:
        """Đếm số lệnh Stop Loss liên tiếp gần nhất"""
        query = """
        SELECT realized_pnl_usd
        FROM trade_signals
        WHERE execution_status = 'CLOSED'
        ORDER BY id DESC
        LIMIT 10
        """
        rows = self._execute(query, fetch="all")
        losses = 0
        for r in rows:
            pnl = r["realized_pnl_usd"]
            if pnl is not None and pnl < 0:
                losses += 1
            else:
                break
        return losses

    def log_audit_event(self, event_type: str, description: str, metadata: Optional[dict] = None):
        """Ghi nhận sự kiện kiểm toán hệ thống"""
        self._execute(
            "INSERT INTO audit_log (event_type, description, metadata) VALUES (?, ?, ?)",
            (event_type, description, json.dumps(metadata or {}))
        )

    def get_journal_stats(self) -> Dict[str, Any]:
        """Tính toán các chỉ số thống kê trading journal (Winrate, Profit Factor)"""
        query = """
        SELECT realized_pnl_usd
        FROM trade_signals
        WHERE execution_status = 'CLOSED' AND realized_pnl_usd IS NOT NULL
        """
        rows = self._execute(query, fetch="all")
        total_trades = len(rows)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "winrate_percent": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "profit_factor": 0.0,
                "net_pnl_usd": 0.0
            }

        pnls = [r["realized_pnl_usd"] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        net_pnl = sum(pnls)

        winrate = (len(wins) / total_trades) * 100.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        return {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "winrate_percent": round(winrate, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "net_pnl_usd": round(net_pnl, 2)
        }
