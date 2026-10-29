#!/usr/bin/env python3
"""Atomic weekly wallet and prize pool accounting per user profile."""

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
DEFAULT_PROFILE_ID = "default"


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
    def __init__(self, db_path: Optional[Path] = None, profile_id: str = DEFAULT_PROFILE_ID):
        self.db_path = Path(db_path or DEFAULT_DB_PATH).expanduser().resolve()
        self.profile_id = str(profile_id or DEFAULT_PROFILE_ID).strip()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ensure_week_initialized()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        return conn

    @contextmanager
    def _transaction(self, conn: Optional[sqlite3.Connection] = None) -> Iterator[sqlite3.Connection]:
        """Own a connection unless a caller supplies one; serialize writers up front."""
        owns_connection = conn is None
        if conn is None:
            conn = self._get_connection()
        if conn.in_transaction:
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
                # 1. Ensure profiles table exists
                conn.execute("""CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    weekly_play_cap REAL NOT NULL DEFAULT 200.0,
                    pin_code TEXT NOT NULL DEFAULT '0000',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL)""")
                if conn.execute("SELECT 1 FROM profiles WHERE id = 'default'").fetchone() is None:
                    now = get_now_iso()
                    conn.execute("""INSERT INTO profiles (id, name, weekly_play_cap, pin_code, created_at, updated_at)
                        VALUES ('default', '主帳號', 200.0, '0000', ?, ?)""", (now, now))

                # 2. Check and migrate wallet_state table
                has_wallet_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wallet_state'").fetchone() is not None
                if not has_wallet_table:
                    conn.execute("""CREATE TABLE wallet_state (
                        profile_id TEXT PRIMARY KEY,
                        current_week TEXT NOT NULL,
                        wallet_balance REAL NOT NULL DEFAULT 0.0,
                        weekly_staked REAL NOT NULL DEFAULT 0.0,
                        prize_pool REAL NOT NULL DEFAULT 0.0,
                        weekly_external_deposited REAL NOT NULL DEFAULT 0.0,
                        weekly_play_cap REAL NOT NULL DEFAULT 200.0,
                        updated_at TEXT NOT NULL)""")
                else:
                    wallet_cols = {r["name"] for r in conn.execute("PRAGMA table_info(wallet_state)").fetchall()}
                    if "profile_id" not in wallet_cols:
                        # Migrate legacy table with id=1
                        conn.execute("ALTER TABLE wallet_state RENAME TO wallet_state_legacy")
                        conn.execute("""CREATE TABLE wallet_state (
                            profile_id TEXT PRIMARY KEY,
                            current_week TEXT NOT NULL,
                            wallet_balance REAL NOT NULL DEFAULT 0.0,
                            weekly_staked REAL NOT NULL DEFAULT 0.0,
                            prize_pool REAL NOT NULL DEFAULT 0.0,
                            weekly_external_deposited REAL NOT NULL DEFAULT 0.0,
                            weekly_play_cap REAL NOT NULL DEFAULT 200.0,
                            updated_at TEXT NOT NULL)""")
                        conn.execute("""INSERT INTO wallet_state (profile_id, current_week, wallet_balance, weekly_staked, prize_pool, weekly_external_deposited, weekly_play_cap, updated_at)
                            SELECT 'default', current_week, wallet_balance, weekly_staked, prize_pool, weekly_external_deposited, 200.0, updated_at
                            FROM wallet_state_legacy""")
                        conn.execute("DROP TABLE wallet_state_legacy")
                    elif "weekly_play_cap" not in wallet_cols:
                        conn.execute("ALTER TABLE wallet_state ADD COLUMN weekly_play_cap REAL NOT NULL DEFAULT 200.0")

                # 3. Check and migrate ledger table
                conn.execute("""CREATE TABLE IF NOT EXISTS ledger (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, week_str TEXT NOT NULL,
                    event_type TEXT NOT NULL, amount REAL NOT NULL, wallet_balance_after REAL NOT NULL,
                    prize_pool_after REAL NOT NULL, notes TEXT NOT NULL DEFAULT '', idempotency_key TEXT,
                    profile_id TEXT NOT NULL DEFAULT 'default')""")
                ledger_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ledger)").fetchall()}
                if "idempotency_key" not in ledger_cols:
                    conn.execute("ALTER TABLE ledger ADD COLUMN idempotency_key TEXT")
                if "profile_id" not in ledger_cols:
                    conn.execute("ALTER TABLE ledger ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'default'")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_idempotency_key ON ledger(idempotency_key) WHERE idempotency_key IS NOT NULL")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_week_str ON ledger(week_str)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON ledger(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_profile ON ledger(profile_id, timestamp)")

                # 4. Check if profile_id row exists in wallet_state
                row = conn.execute("SELECT 1 FROM wallet_state WHERE profile_id = ?", (self.profile_id,)).fetchone()
                if row is None:
                    prow = conn.execute("SELECT weekly_play_cap FROM profiles WHERE id = ?", (self.profile_id,)).fetchone()
                    cap = float(prow["weekly_play_cap"]) if prow else WEEKLY_PLAY_CAP
                    conn.execute("""INSERT INTO wallet_state (profile_id, current_week, wallet_balance, weekly_staked, prize_pool, weekly_external_deposited, weekly_play_cap, updated_at)
                        VALUES (?, ?, 0, 0, 0, 0, ?, ?)""", (self.profile_id, get_current_iso_week(), cap, get_now_iso()))
        finally:
            conn.close()

    def _state(self, conn: sqlite3.Connection, target_date: Optional[date] = None) -> Dict[str, Any]:
        self._ensure_week_initialized(target_date, conn=conn)
        row = conn.execute("SELECT * FROM wallet_state WHERE profile_id = ?", (self.profile_id,)).fetchone()
        if row is None:
            prow = conn.execute("SELECT weekly_play_cap FROM profiles WHERE id = ?", (self.profile_id,)).fetchone()
            cap = float(prow["weekly_play_cap"]) if prow else WEEKLY_PLAY_CAP
            conn.execute("""INSERT INTO wallet_state (profile_id, current_week, wallet_balance, weekly_staked, prize_pool, weekly_external_deposited, weekly_play_cap, updated_at)
                VALUES (?, ?, 0, 0, 0, 0, ?, ?)""", (self.profile_id, get_current_iso_week(target_date), cap, get_now_iso()))
            row = conn.execute("SELECT * FROM wallet_state WHERE profile_id = ?", (self.profile_id,)).fetchone()
        return dict(row)

    def _ensure_week_initialized(self, target_date: Optional[date] = None, conn: Optional[sqlite3.Connection] = None) -> None:
        now_week = get_current_iso_week(target_date)
        with self._transaction(conn) as tx:
            row = tx.execute("SELECT * FROM wallet_state WHERE profile_id = ?", (self.profile_id,)).fetchone()
            if row is None:
                prow = tx.execute("SELECT weekly_play_cap FROM profiles WHERE id = ?", (self.profile_id,)).fetchone()
                cap = float(prow["weekly_play_cap"]) if prow else WEEKLY_PLAY_CAP
                tx.execute("""INSERT INTO wallet_state (profile_id, current_week, wallet_balance, weekly_staked, prize_pool, weekly_external_deposited, weekly_play_cap, updated_at)
                    VALUES (?, ?, 0, 0, 0, 0, ?, ?)""", (self.profile_id, now_week, cap, get_now_iso()))
                row = tx.execute("SELECT * FROM wallet_state WHERE profile_id = ?", (self.profile_id,)).fetchone()
            state = dict(row)
            if state["current_week"] == now_week:
                return
            # Preserve the existing rollover rule: top the wallet up to weekly_play_cap from reserve.
            play_cap = float(state.get("weekly_play_cap", WEEKLY_PLAY_CAP))
            old_wallet = float(state["wallet_balance"])
            pool = float(state["prize_pool"])
            draw = min(max(0.0, play_cap - old_wallet), max(0.0, pool))
            wallet_after = round(old_wallet + draw, 2)
            pool_after = round(pool - draw, 2)
            now = get_now_iso()
            tx.execute("""UPDATE wallet_state SET current_week=?, wallet_balance=?, weekly_staked=0,
                prize_pool=?, weekly_external_deposited=0, updated_at=? WHERE profile_id=?""",
                (now_week, wallet_after, pool_after, now, self.profile_id))
            if draw > 0:
                tx.execute("""INSERT INTO ledger (id,timestamp,week_str,event_type,amount,wallet_balance_after,prize_pool_after,notes,profile_id)
                    VALUES (?,?,?,'WEEKLY_ROLLOVER',?,?,?,?,?)""",
                    (str(uuid.uuid4()), now, now_week, draw, wallet_after, pool_after,
                     f"新週啟動：從獲利池調撥 NT$ {draw:.2f} 作為本週預算", self.profile_id))

    @staticmethod
    def _external_remaining(state: Dict[str, Any]) -> float:
        play_cap = float(state.get("weekly_play_cap", WEEKLY_PLAY_CAP))
        committed = float(state["wallet_balance"]) + float(state["weekly_staked"])
        shortfall = max(0.0, play_cap - committed)
        return max(0.0, min(shortfall, play_cap - float(state["weekly_external_deposited"])))

    def get_status(self) -> Dict[str, Any]:
        with self._transaction() as conn:
            state = self._state(conn)
            ledger_rows = conn.execute("SELECT event_type, amount FROM ledger WHERE profile_id = ?", (self.profile_id,)).fetchall()
        wallet_bal = float(state["wallet_balance"])
        staked = float(state["weekly_staked"])
        prize_pool = float(state["prize_pool"])
        ext_dep = float(state["weekly_external_deposited"])
        play_cap = float(state.get("weekly_play_cap", WEEKLY_PLAY_CAP))
        sums = {"EXTERNAL_DEPOSIT": 0.0, "BET_STAKE": 0.0, "BET_PAYOUT": 0.0, "WITHDRAW_PROFIT": 0.0}
        for r in ledger_rows:
            et, amt = r["event_type"], float(r["amount"])
            if et in sums:
                sums[et] += abs(amt) if et in ("BET_STAKE", "WITHDRAW_PROFIT") else amt
        remaining = self._external_remaining(state)
        return {
            "profile_id": self.profile_id,
            "current_week": state["current_week"], "weekly_wallet_balance": round(wallet_bal, 2),
            "weekly_staked": round(staked, 2), "prize_pool": round(prize_pool, 2),
            "reserve_balance": round(prize_pool, 2), "weekly_external_deposited": round(ext_dep, 2),
            "weekly_play_cap": play_cap, "external_deposit_remaining": round(remaining, 2),
            "can_deposit": remaining > 0, "can_bet": wallet_bal > 0,
            "lifetime_external_deposited": round(sums["EXTERNAL_DEPOSIT"], 2),
            "lifetime_staked": round(sums["BET_STAKE"], 2),
            "lifetime_gross_payout": round(sums["BET_PAYOUT"], 2),
            "lifetime_net_profit": round(sums["BET_PAYOUT"] - sums["BET_STAKE"], 2),
            "lifetime_withdrawn": round(sums["WITHDRAW_PROFIT"], 2),
        }

    def _insert_ledger(self, conn: sqlite3.Connection, week: str, event_type: str, amount: float,
                       wallet: float, pool: float, notes: str, idempotency_key: Optional[str] = None) -> None:
        conn.execute("""INSERT INTO ledger (id,timestamp,week_str,event_type,amount,wallet_balance_after,prize_pool_after,notes,idempotency_key,profile_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), get_now_iso(), week, event_type, amount, wallet, pool, notes, idempotency_key, self.profile_id))

    def deposit_external(self, amount: float, notes: str = "") -> Dict[str, Any]:
        amount = _money(amount, "入金金額")
        with self._transaction() as conn:
            state = self._state(conn)
            remaining = self._external_remaining(state)
            play_cap = float(state.get("weekly_play_cap", WEEKLY_PLAY_CAP))
            if amount > remaining + 1e-9:
                raise ValueError(f"【入金上限攔截】本週外部入金額度剩餘 NT$ {remaining:.2f}。風控鐵律：每週最多只允許 NT$ {play_cap:.2f} 進入戰場！")
            wallet = round(float(state["wallet_balance"]) + amount, 2)
            deposited = round(float(state["weekly_external_deposited"]) + amount, 2)
            conn.execute("UPDATE wallet_state SET wallet_balance=?,weekly_external_deposited=?,updated_at=? WHERE profile_id=?", (wallet, deposited, get_now_iso(), self.profile_id))
            self._insert_ledger(conn, state["current_week"], "EXTERNAL_DEPOSIT", amount, wallet, float(state["prize_pool"]), notes or f"外部入金 NT$ {amount:.2f}")
        return {"success": True, "amount": amount, "new_wallet_balance": wallet, "weekly_external_deposited": deposited, "profile_id": self.profile_id}

    def stake_bet(self, stake: float, ticket_id: str, notes: str = "", *, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        stake = _money(stake, "下注金額")
        with self._transaction(conn) as tx:
            state = self._state(tx)
            balance = float(state["wallet_balance"])
            play_cap = float(state.get("weekly_play_cap", WEEKLY_PLAY_CAP))
            week_room = max(0.0, play_cap - float(state["weekly_staked"]))
            if stake > balance + 1e-9 or stake > week_room + 1e-9:
                raise ValueError(f"【本週預算不足】目前本週可玩餘額僅 NT$ {balance:.2f}，無法下注 NT$ {stake:.2f}。風控規則：每週僅能玩 NT$ {play_cap:.2f}。沒錢了就必須等待下週刷新！")
            wallet = round(balance - stake, 2)
            staked = round(float(state["weekly_staked"]) + stake, 2)
            tx.execute("UPDATE wallet_state SET wallet_balance=?,weekly_staked=?,updated_at=? WHERE profile_id=?", (wallet, staked, get_now_iso(), self.profile_id))
            self._insert_ledger(tx, state["current_week"], "BET_STAKE", -stake, wallet, float(state["prize_pool"]), notes or f"注單扣款 #{ticket_id[:8]}", f"ticket:{ticket_id}:stake")
        return {"success": True, "stake": stake, "new_wallet_balance": wallet, "weekly_staked": staked, "profile_id": self.profile_id}

    def credit_winnings(self, payout: float, ticket_id: str, notes: str = "", *, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        payout = float(payout)
        if not math.isfinite(payout) or payout < 0:
            raise ValueError("派彩金額必須是有限的非負數。")
        payout = round(payout + 1e-10, 2)
        if payout == 0:
            return {"success": True, "payout": 0.0, "profile_id": self.profile_id}
        with self._transaction(conn) as tx:
            state = self._state(tx)
            pool = round(float(state["prize_pool"]) + payout, 2)
            wallet = float(state["wallet_balance"])
            tx.execute("UPDATE wallet_state SET prize_pool=?,updated_at=? WHERE profile_id=?", (pool, get_now_iso(), self.profile_id))
            self._insert_ledger(tx, state["current_week"], "BET_PAYOUT", payout, wallet, pool, notes or f"注單中獎派彩 #{ticket_id[:8]} 鎖入獲利池", f"ticket:{ticket_id}:payout")
        return {"success": True, "payout": payout, "new_prize_pool": pool, "profile_id": self.profile_id}

    def withdraw_from_prize_pool(self, amount: float) -> Dict[str, Any]:
        amount = _money(amount, "提領金額")
        with self._transaction() as conn:
            state = self._state(conn)
            pool_before = float(state["prize_pool"])
            if amount > pool_before + 1e-9:
                raise ValueError(f"獲利保留池僅有 NT$ {pool_before:.2f}，不足提領 NT$ {amount:.2f}。")
            pool = round(pool_before - amount, 2)
            wallet = float(state["wallet_balance"])
            conn.execute("UPDATE wallet_state SET prize_pool=?,updated_at=? WHERE profile_id=?", (pool, get_now_iso(), self.profile_id))
            self._insert_ledger(conn, state["current_week"], "WITHDRAW_PROFIT", -amount, wallet, pool, f"提領獲利 NT$ {amount:.2f} 至主要資產")
        return {"success": True, "amount": amount, "new_prize_pool": pool, "profile_id": self.profile_id}

    def get_ledger_history(self, limit: int = 50, profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        pid = profile_id or self.profile_id
        try:
            if pid == "all":
                rows = conn.execute("SELECT * FROM ledger ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM ledger WHERE profile_id = ? ORDER BY timestamp DESC LIMIT ?", (pid, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


WalletManager = WeeklyWalletManager
