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
            conn.commit()
        finally:
            conn.close()

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
