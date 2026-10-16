#!/usr/bin/env python3
"""War Chest Capital Control & Ledger for Sports Lottery.

Inherited from the Risk Lab philosophy (C:\\Projects\\PythonProjects\\risk lab):
- Highest Principle: "允許高風險，禁止無邊界。" (Allow high risk, forbid unbounded risk).
- Weekly Deposit Cap: Maximum NT$ 200 per calendar week (ISO week).
  The user is NOT forced to deposit every week.
- Surplus Re-investment: "多餘的才可以再繼續"
  Only accumulated profits and available bankroll can be used to continue betting.
  Once available balance hits 0 and the week's 200 quota is used, betting is strictly locked.
- Local SQLite Ledger: Zero broker / zero external dependency.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.storage_config import get_db_path

WEEKLY_DEPOSIT_CAP = 200.0
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = get_db_path()


def get_current_week_str(target_date: Optional[date] = None) -> str:
    """Return ISO week format, e.g., '2026-W38'."""
    d = target_date or date.today()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WarChestManager:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cash_flows (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    flow_time TEXT NOT NULL,
                    flow_type TEXT NOT NULL CHECK (flow_type IN ('DEPOSIT', 'WITHDRAWAL', 'BET_STAKE', 'BET_PAYOUT', 'ADJUSTMENT')),
                    week_str TEXT NOT NULL,
                    amount REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    ticket_id TEXT,
                    notes TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    week_str TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('OPEN', 'WON', 'LOST', 'VOID')),
                    stake REAL NOT NULL,
                    total_odds REAL NOT NULL,
                    potential_payout REAL NOT NULL,
                    actual_payout REAL NOT NULL DEFAULT 0.0,
                    settled_at TEXT,
                    legs_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.commit()

    def get_latest_balance(self) -> float:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT balance_after FROM cash_flows ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row:
                return float(row["balance_after"])
            return 0.0

    def get_week_deposits(self, week_str: Optional[str] = None) -> float:
        week = week_str or get_current_week_str()
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT SUM(amount) as total
                FROM cash_flows
                WHERE flow_type = 'DEPOSIT' AND week_str = ?
                """,
                (week,),
            ).fetchone()
            return float(row["total"]) if row and row["total"] is not None else 0.0

    def deposit(self, amount: float, notes: str = "", target_date: Optional[date] = None) -> Dict[str, Any]:
        """Deposit funds into the War Chest with weekly cap verification."""
        if amount <= 0:
            raise ValueError("入金金額必須大於 0 元。")
        amount = round(amount, 2)
        week_str = get_current_week_str(target_date)
        already_deposited = self.get_week_deposits(week_str)
        remaining_quota = max(0.0, WEEKLY_DEPOSIT_CAP - already_deposited)

        if amount > remaining_quota:
            raise ValueError(
                f"【風控攔截】本週 ({week_str}) 已入金 NT$ {already_deposited:.2f}，"
                f"剩餘額度僅 NT$ {remaining_quota:.2f}。不能超過每週上限 NT$ {WEEKLY_DEPOSIT_CAP:.2f}！"
            )

        current_balance = self.get_latest_balance()
        new_balance = round(current_balance + amount, 2)
        flow_id = str(uuid.uuid4())
        now_iso = get_now_iso()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cash_flows (id, created_at, flow_time, flow_type, week_str, amount, balance_after, notes)
                VALUES (?, ?, ?, 'DEPOSIT', ?, ?, ?, ?)
                """,
                (flow_id, now_iso, now_iso, week_str, amount, new_balance, notes or f"每週入金 ({week_str})"),
            )
            conn.commit()

        return {
            "success": True,
            "flow_id": flow_id,
            "amount": amount,
            "balance_after": new_balance,
            "week_str": week_str,
            "week_deposit_remaining": round(remaining_quota - amount, 2),
        }

    def withdraw(self, amount: float, notes: str = "") -> Dict[str, Any]:
        """Withdraw surplus funds to main assets."""
        if amount <= 0:
            raise ValueError("提領金額必須大於 0 元。")
        amount = round(amount, 2)
        current_balance = self.get_latest_balance()

        if amount > current_balance:
            raise ValueError(f"【提領失敗】可用餘額僅 NT$ {current_balance:.2f}，不足提領 NT$ {amount:.2f}！")

        new_balance = round(current_balance - amount, 2)
        flow_id = str(uuid.uuid4())
        now_iso = get_now_iso()
        week_str = get_current_week_str()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cash_flows (id, created_at, flow_time, flow_type, week_str, amount, balance_after, notes)
                VALUES (?, ?, ?, 'WITHDRAWAL', ?, ?, ?, ?)
                """,
                (flow_id, now_iso, now_iso, week_str, -amount, new_balance, notes or "利潤提領至主要資產"),
            )
            conn.commit()

        return {
            "success": True,
            "flow_id": flow_id,
            "amount": amount,
            "balance_after": new_balance,
        }

    def commit_bet(self, stake: float, ticket_id: str, notes: str = "") -> Dict[str, Any]:
        """Deduct stake from War Chest for a confirmed ticket."""
        if stake <= 0:
            raise ValueError("下注金額必須大於 0 元。")
        stake = round(stake, 2)
        current_balance = self.get_latest_balance()

        if stake > current_balance:
            week_str = get_current_week_str()
            deposited = self.get_week_deposits(week_str)
            quota_left = max(0.0, WEEKLY_DEPOSIT_CAP - deposited)
            hint = f"（本週尚有入金額度 NT$ {quota_left:.2f}，可先進行每週入金）" if quota_left > 0 else "（本週 NT$ 200 入金限額已滿，請等待下週）"
            raise ValueError(
                f"【資金不足】資金庫可用餘額為 NT$ {current_balance:.2f}，無法下注 NT$ {stake:.2f}！\n"
                f"風控規則：多餘贏利或本週合法入金才可下注。{hint}"
            )

        new_balance = round(current_balance - stake, 2)
        flow_id = str(uuid.uuid4())
        now_iso = get_now_iso()
        week_str = get_current_week_str()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cash_flows (id, created_at, flow_time, flow_type, week_str, amount, balance_after, ticket_id, notes)
                VALUES (?, ?, ?, 'BET_STAKE', ?, ?, ?, ?, ?)
                """,
                (flow_id, now_iso, now_iso, week_str, -stake, new_balance, ticket_id, notes or f"下注扣款 #{ticket_id[:8]}"),
            )
            conn.commit()

        return {
            "success": True,
            "flow_id": flow_id,
            "stake": stake,
            "balance_after": new_balance,
        }

    def settle_bet(self, ticket_id: str, won: bool, payout: float = 0.0, notes: str = "") -> Dict[str, Any]:
        """Settle an open bet. If won, credit payout back to War Chest."""
        now_iso = get_now_iso()
        week_str = get_current_week_str()
        current_balance = self.get_latest_balance()
        payout = round(payout, 2) if won else 0.0
        new_balance = round(current_balance + payout, 2)
        status = "WON" if won else "LOST"

        with self._get_connection() as conn:
            # Update ticket
            conn.execute(
                """
                UPDATE tickets
                SET status = ?, actual_payout = ?, settled_at = ?, notes = notes || ' ' || ?
                WHERE id = ?
                """,
                (status, payout, now_iso, notes, ticket_id),
            )
            flow_id = None
            if won and payout > 0:
                flow_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO cash_flows (id, created_at, flow_time, flow_type, week_str, amount, balance_after, ticket_id, notes)
                    VALUES (?, ?, ?, 'BET_PAYOUT', ?, ?, ?, ?, ?)
                    """,
                    (flow_id, now_iso, now_iso, week_str, payout, new_balance, ticket_id, notes or f"注單中獎派彩 #{ticket_id[:8]}"),
                )
            conn.commit()

        return {
            "success": True,
            "status": status,
            "payout": payout,
            "balance_after": new_balance,
            "flow_id": flow_id,
        }

    def get_status(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Get complete War Chest status dashboard data."""
        week_str = get_current_week_str(target_date)
        balance = self.get_latest_balance()
        week_deposited = self.get_week_deposits(week_str)
        week_deposit_remaining = max(0.0, WEEKLY_DEPOSIT_CAP - week_deposited)

        with self._get_connection() as conn:
            # Totals
            total_dep = conn.execute("SELECT SUM(amount) as t FROM cash_flows WHERE flow_type = 'DEPOSIT'").fetchone()["t"] or 0.0
            total_wd = conn.execute("SELECT SUM(abs(amount)) as t FROM cash_flows WHERE flow_type = 'WITHDRAWAL'").fetchone()["t"] or 0.0
            total_staked = conn.execute("SELECT SUM(abs(amount)) as t FROM cash_flows WHERE flow_type = 'BET_STAKE'").fetchone()["t"] or 0.0
            total_payout = conn.execute("SELECT SUM(amount) as t FROM cash_flows WHERE flow_type = 'BET_PAYOUT'").fetchone()["t"] or 0.0

            # Ticket stats
            total_tickets = conn.execute("SELECT COUNT(*) as c FROM tickets").fetchone()["c"] or 0
            won_tickets = conn.execute("SELECT COUNT(*) as c FROM tickets WHERE status = 'WON'").fetchone()["c"] or 0
            lost_tickets = conn.execute("SELECT COUNT(*) as c FROM tickets WHERE status = 'LOST'").fetchone()["c"] or 0
            open_tickets = conn.execute("SELECT COUNT(*) as c FROM tickets WHERE status = 'OPEN'").fetchone()["c"] or 0

        # Net Profit = (Available Balance + Total Withdrawn) - Total Deposited
        net_profit = round((balance + total_wd) - total_dep, 2)
        roi = round((net_profit / total_dep * 100.0), 1) if total_dep > 0 else 0.0
        win_rate = round((won_tickets / (won_tickets + lost_tickets) * 100.0), 1) if (won_tickets + lost_tickets) > 0 else 0.0

        return {
            "available_balance": balance,
            "week_str": week_str,
            "weekly_cap": WEEKLY_DEPOSIT_CAP,
            "week_deposited": round(week_deposited, 2),
            "week_deposit_remaining": round(week_deposit_remaining, 2),
            "can_deposit": week_deposit_remaining > 0,
            "total_deposited": round(total_dep, 2),
            "total_withdrawn": round(total_wd, 2),
            "total_staked": round(total_staked, 2),
            "total_payout": round(total_payout, 2),
            "net_profit": net_profit,
            "roi_percent": roi,
            "tickets": {
                "total": total_tickets,
                "open": open_tickets,
                "won": won_tickets,
                "lost": lost_tickets,
                "win_rate": win_rate,
            },
        }

    def get_cash_flows(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cash_flows ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
