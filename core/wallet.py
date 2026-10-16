#!/usr/bin/env python3
"""Atomic weekly wallet and prize pool accounting."""

from __future__ import annotations

import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from core.storage_config import get_db_path

WEEKLY_PLAY_CAP = 200.0
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = get_db_path()


def get_current_iso_week(target_date: Optional[date] = None) -> str:
    d = target_date or date.today()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value: float, label: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label}必須是有限的正數。") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError(f"{label}必須是有限的正數。")
    rounded = round(amount + 1e-10, 2)
    if rounded <= 0:
        raise ValueError(f"{label}至少為 NT$ 0.01。")
    return rounded


class WeeklyWalletManager:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ensure_week_initialized()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _transaction(self, conn: Optional[sqlite3.Connection] = None) -> Iterator[sqlite3.Connection]:
        """Own a connection unless a caller supplies one; serialize writers up front."""
        owns_connection = conn is None
        if conn is None:
            conn = self._get_connection()
        if conn.in_transaction:
            # A recorder may pass its already-locked connection so ticket and
            # wallet writes share one SQLite transaction.
            yield conn
            return
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with self._transaction(conn):
                conn.execute("""CREATE TABLE IF NOT EXISTS wallet_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1), current_week TEXT NOT NULL,
                    wallet_balance REAL NOT NULL DEFAULT 0.0, weekly_staked REAL NOT NULL DEFAULT 0.0,
                    prize_pool REAL NOT NULL DEFAULT 0.0, weekly_external_deposited REAL NOT NULL DEFAULT 0.0,
                    updated_at TEXT NOT NULL)""")
                conn.execute("""CREATE TABLE IF NOT EXISTS ledger (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, week_str TEXT NOT NULL,
                    event_type TEXT NOT NULL, amount REAL NOT NULL, wallet_balance_after REAL NOT NULL,
                    prize_pool_after REAL NOT NULL, notes TEXT NOT NULL DEFAULT '', idempotency_key TEXT)""")
                columns = {r["name"] for r in conn.execute("PRAGMA table_info(ledger)")}
                if "idempotency_key" not in columns:
                    conn.execute("ALTER TABLE ledger ADD COLUMN idempotency_key TEXT")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_idempotency_key ON ledger(idempotency_key) WHERE idempotency_key IS NOT NULL")
                if conn.execute("SELECT 1 FROM wallet_state WHERE id = 1").fetchone() is None:
                    conn.execute("INSERT INTO wallet_state (id,current_week,wallet_balance,weekly_staked,prize_pool,weekly_external_deposited,updated_at) VALUES (1,?,0,0,0,0,?)", (get_current_iso_week(), get_now_iso()))
        finally:
            conn.close()

    def _state(self, conn: sqlite3.Connection, target_date: Optional[date] = None) -> Dict[str, Any]:
        self._ensure_week_initialized(target_date, conn=conn)
        row = conn.execute("SELECT * FROM wallet_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("錢包狀態資料不存在。")
        return dict(row)

    def _ensure_week_initialized(self, target_date: Optional[date] = None, conn: Optional[sqlite3.Connection] = None) -> None:
        now_week = get_current_iso_week(target_date)
        with self._transaction(conn) as tx:
            row = tx.execute("SELECT * FROM wallet_state WHERE id = 1").fetchone()
            if row is None:
                raise RuntimeError("錢包狀態資料不存在。")
            state = dict(row)
            if state["current_week"] == now_week:
                return
            # Preserve the existing rollover rule: top the wallet up to 200 from reserve.
            old_wallet = float(state["wallet_balance"])
            pool = float(state["prize_pool"])
            draw = min(max(0.0, WEEKLY_PLAY_CAP - old_wallet), max(0.0, pool))
            wallet_after = round(old_wallet + draw, 2)
            pool_after = round(pool - draw, 2)
            now = get_now_iso()
            tx.execute("""UPDATE wallet_state SET current_week=?, wallet_balance=?, weekly_staked=0,
                prize_pool=?, weekly_external_deposited=0, updated_at=? WHERE id=1""",
                (now_week, wallet_after, pool_after, now))
            if draw > 0:
                tx.execute("""INSERT INTO ledger (id,timestamp,week_str,event_type,amount,wallet_balance_after,prize_pool_after,notes)
                    VALUES (?,?,?,'WEEKLY_ROLLOVER',?,?,?,?)""",
                    (str(uuid.uuid4()), now, now_week, draw, wallet_after, pool_after,
                     f"新週啟動：從獲利池調撥 NT$ {draw:.2f} 作為本週預算"))

    @staticmethod
    def _external_remaining(state: Dict[str, Any]) -> float:
        committed = float(state["wallet_balance"]) + float(state["weekly_staked"])
        shortfall = max(0.0, WEEKLY_PLAY_CAP - committed)
        return max(0.0, min(shortfall, WEEKLY_PLAY_CAP - float(state["weekly_external_deposited"])))

    def get_status(self) -> Dict[str, Any]:
        with self._transaction() as conn:
            state = self._state(conn)
            ledger_rows = conn.execute("SELECT event_type, amount FROM ledger").fetchall()
        wallet_bal = float(state["wallet_balance"])
        staked = float(state["weekly_staked"])
        prize_pool = float(state["prize_pool"])
        ext_dep = float(state["weekly_external_deposited"])
        sums = {"EXTERNAL_DEPOSIT": 0.0, "BET_STAKE": 0.0, "BET_PAYOUT": 0.0, "WITHDRAW_PROFIT": 0.0}
        for r in ledger_rows:
            et, amt = r["event_type"], float(r["amount"])
            if et in sums:
                sums[et] += abs(amt) if et in ("BET_STAKE", "WITHDRAW_PROFIT") else amt
        remaining = self._external_remaining(state)
        return {
            "current_week": state["current_week"], "weekly_wallet_balance": round(wallet_bal, 2),
            "weekly_staked": round(staked, 2), "prize_pool": round(prize_pool, 2),
            "reserve_balance": round(prize_pool, 2), "weekly_external_deposited": round(ext_dep, 2),
            "weekly_play_cap": WEEKLY_PLAY_CAP, "external_deposit_remaining": round(remaining, 2),
            "can_deposit": remaining > 0, "can_bet": wallet_bal > 0,
            "lifetime_external_deposited": round(sums["EXTERNAL_DEPOSIT"], 2),
            "lifetime_staked": round(sums["BET_STAKE"], 2),
            "lifetime_gross_payout": round(sums["BET_PAYOUT"], 2),
            "lifetime_net_profit": round(sums["BET_PAYOUT"] - sums["BET_STAKE"], 2),
            "lifetime_withdrawn": round(sums["WITHDRAW_PROFIT"], 2),
        }

    @staticmethod
    def _insert_ledger(conn: sqlite3.Connection, week: str, event_type: str, amount: float,
                       wallet: float, pool: float, notes: str, idempotency_key: Optional[str] = None) -> None:
        conn.execute("""INSERT INTO ledger (id,timestamp,week_str,event_type,amount,wallet_balance_after,prize_pool_after,notes,idempotency_key)
            VALUES (?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), get_now_iso(), week, event_type, amount, wallet, pool, notes, idempotency_key))

    def deposit_external(self, amount: float, notes: str = "") -> Dict[str, Any]:
        amount = _money(amount, "入金金額")
        with self._transaction() as conn:
            state = self._state(conn)
            remaining = self._external_remaining(state)
            if amount > remaining + 1e-9:
                raise ValueError(f"【入金上限攔截】本週外部入金額度剩餘 NT$ {remaining:.2f}。風控鐵律：每週最多只允許 NT$ {WEEKLY_PLAY_CAP:.2f} 進入戰場！")
            wallet = round(float(state["wallet_balance"]) + amount, 2)
            deposited = round(float(state["weekly_external_deposited"]) + amount, 2)
            conn.execute("UPDATE wallet_state SET wallet_balance=?,weekly_external_deposited=?,updated_at=? WHERE id=1", (wallet, deposited, get_now_iso()))
            self._insert_ledger(conn, state["current_week"], "EXTERNAL_DEPOSIT", amount, wallet, float(state["prize_pool"]), notes or f"外部入金 NT$ {amount:.2f}")
        return {"success": True, "amount": amount, "new_wallet_balance": wallet, "weekly_external_deposited": deposited}

    def stake_bet(self, stake: float, ticket_id: str, notes: str = "", *, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        stake = _money(stake, "下注金額")
        with self._transaction(conn) as tx:
            state = self._state(tx)
            balance = float(state["wallet_balance"])
            week_room = max(0.0, WEEKLY_PLAY_CAP - float(state["weekly_staked"]))
            if stake > balance + 1e-9 or stake > week_room + 1e-9:
                raise ValueError(f"【本週預算不足】目前本週可玩餘額僅 NT$ {balance:.2f}，無法下注 NT$ {stake:.2f}。風控規則：每週僅能玩 NT$ 200。沒錢了就必須等待下週刷新！")
            wallet = round(balance - stake, 2)
            staked = round(float(state["weekly_staked"]) + stake, 2)
            tx.execute("UPDATE wallet_state SET wallet_balance=?,weekly_staked=?,updated_at=? WHERE id=1", (wallet, staked, get_now_iso()))
            self._insert_ledger(tx, state["current_week"], "BET_STAKE", -stake, wallet, float(state["prize_pool"]), notes or f"注單扣款 #{ticket_id[:8]}", f"ticket:{ticket_id}:stake")
        return {"success": True, "stake": stake, "new_wallet_balance": wallet, "weekly_staked": staked}

    def credit_winnings(self, payout: float, ticket_id: str, notes: str = "", *, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        payout = float(payout)
        if not math.isfinite(payout) or payout < 0:
            raise ValueError("派彩金額必須是有限的非負數。")
        payout = round(payout + 1e-10, 2)
        if payout == 0:
            return {"success": True, "payout": 0.0}
        with self._transaction(conn) as tx:
            state = self._state(tx)
            pool = round(float(state["prize_pool"]) + payout, 2)
            wallet = float(state["wallet_balance"])
            tx.execute("UPDATE wallet_state SET prize_pool=?,updated_at=? WHERE id=1", (pool, get_now_iso()))
            self._insert_ledger(tx, state["current_week"], "BET_PAYOUT", payout, wallet, pool, notes or f"注單中獎派彩 #{ticket_id[:8]} 鎖入獲利池", f"ticket:{ticket_id}:payout")
        return {"success": True, "payout": payout, "new_prize_pool": pool}

    def withdraw_from_prize_pool(self, amount: float) -> Dict[str, Any]:
        amount = _money(amount, "提領金額")
        with self._transaction() as conn:
            state = self._state(conn)
            pool_before = float(state["prize_pool"])
            if amount > pool_before + 1e-9:
                raise ValueError(f"獲利保留池僅有 NT$ {pool_before:.2f}，不足提領 NT$ {amount:.2f}。")
            pool = round(pool_before - amount, 2)
            wallet = float(state["wallet_balance"])
            conn.execute("UPDATE wallet_state SET prize_pool=?,updated_at=? WHERE id=1", (pool, get_now_iso()))
            self._insert_ledger(conn, state["current_week"], "WITHDRAW_PROFIT", -amount, wallet, pool, f"提領獲利 NT$ {amount:.2f} 至主要資產")
        return {"success": True, "amount": amount, "new_prize_pool": pool}

    def get_ledger_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT * FROM ledger ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


WalletManager = WeeklyWalletManager
