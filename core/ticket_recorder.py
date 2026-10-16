#!/usr/bin/env python3
"""Ticket recording and settlement backed by the atomic wallet ledger."""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .wallet import DEFAULT_DB_PATH, WeeklyWalletManager, _money, get_current_iso_week, get_now_iso


class TicketRecorder:
    def __init__(self, wallet: Optional[WeeklyWalletManager] = None, db_path: Optional[Path] = None):
        if wallet is not None and db_path is not None:
            requested = Path(db_path).expanduser().resolve()
            if requested != wallet.db_path:
                raise ValueError("錢包與注單必須使用同一個 SQLite 資料庫，才能保證原子交易。")
        self.wallet = wallet or WeeklyWalletManager(db_path=db_path)
        self.db_path = Path(db_path or self.wallet.db_path or DEFAULT_DB_PATH).expanduser().resolve()
        if self.db_path != self.wallet.db_path:
            raise ValueError("錢包與注單必須使用同一個 SQLite 資料庫，才能保證原子交易。")
        self._init_tickets_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tickets_table(self) -> None:
        conn = self._get_connection()
        try:
            with self._transaction_on(conn):
                conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, week_str TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('OPEN', 'WON', 'LOST', 'VOID')),
                    stake REAL NOT NULL, total_odds REAL NOT NULL, recommendation_odds REAL,
                    placed_odds REAL, closing_odds REAL, clv REAL, potential_payout REAL NOT NULL,
                    actual_payout REAL NOT NULL DEFAULT 0.0, settled_at TEXT,
                    sports_summary TEXT NOT NULL DEFAULT '', legs_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '', entry_mode TEXT NOT NULL DEFAULT 'manual', idempotency_key TEXT)""")
                columns = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
                for name, sql_type in (("recommendation_odds", "REAL"), ("placed_odds", "REAL"),
                                       ("closing_odds", "REAL"), ("clv", "REAL"),
                                       ("entry_mode", "TEXT NOT NULL DEFAULT 'manual'"),
                                       ("idempotency_key", "TEXT"), ("settled_at", "TEXT")):
                    if name not in columns:
                        conn.execute(f"ALTER TABLE tickets ADD COLUMN {name} {sql_type}")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_idempotency_key ON tickets(idempotency_key) WHERE idempotency_key IS NOT NULL")
        finally:
            conn.close()

    @staticmethod
    @contextmanager
    def _transaction_on(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise

    @staticmethod
    def _ticket_dict(row: sqlite3.Row) -> Dict[str, Any]:
        ticket = dict(row)
        try:
            ticket["legs"] = json.loads(ticket.get("legs_json", "[]"))
        except (TypeError, json.JSONDecodeError):
            ticket["legs"] = []
        return ticket

    @staticmethod
    def _business_legs(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identity fields stay stable when a retry refreshes odds timestamps/metadata."""
        fields = ("canonical_event_id", "event_id", "match_id", "sport", "league",
                  "home_team", "away_team", "market", "market_type", "selection", "side", "line")
        return [{key: leg.get(key) for key in fields} for leg in legs]

    def place_ticket(
        self,
        legs: List[Dict[str, Any]],
        stake: float,
        total_odds: float,
        recommendation_odds: Optional[float] = None,
        placed_odds: Optional[float] = None,
        notes: str = "",
        entry_mode: str = "manual",
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a locally confirmed ticket; this does not place an official wager."""
        stake = _money(stake, "注金")
        try:
            total_odds = float(total_odds)
            rec_raw = recommendation_odds if recommendation_odds is not None else total_odds
            plc_raw = placed_odds if placed_odds is not None else rec_raw
            rec_raw, plc_raw = float(rec_raw), float(plc_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("賠率必須是有限的正數。") from exc
        if not all(math.isfinite(v) and v > 1.0 for v in (total_odds, rec_raw, plc_raw)):
            raise ValueError("總賠率必須是大於 1.0 的有限數值。")
        if not legs:
            raise ValueError("注單必須包含至少 1 個賽事關卡。")
        if entry_mode not in ("manual", "recommendation"):
            raise ValueError("entry_mode 僅支援 manual 或 recommendation。")
        if idempotency_key is not None:
            idempotency_key = str(idempotency_key).strip()
            if not idempotency_key:
                raise ValueError("idempotency_key 不可為空字串。")

        rec_odds, plc_odds = round(rec_raw, 2), round(plc_raw, 2)
        if rec_odds <= 1.0 or plc_odds <= 1.0:
            raise ValueError("總賠率必須大於 1.0。")
        effective_odds = plc_odds
        raw_potential_payout = stake * effective_odds
        if not math.isfinite(raw_potential_payout):
            raise ValueError("預計派彩金額超出有限數值範圍。")
        potential_payout = round(raw_potential_payout, 2)
        ticket_id, now_iso = str(uuid.uuid4()), get_now_iso()
        leagues: List[str] = []
        for leg in legs:
            league = leg.get("league", "")
            cleaned = league.split()[0] if league else "賽事"
            if cleaned not in leagues:
                leagues.append(cleaned)
        sports_summary = " + ".join(leagues)
        legs_json = json.dumps(legs, ensure_ascii=False)

        with self._transaction() as conn:
            # Resolve retries before recommendation freshness checks: a successful
            # earlier submission remains successful even after kickoff.
            if idempotency_key is not None:
                existing = conn.execute("SELECT * FROM tickets WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing:
                    result = self._ticket_dict(existing)
                    same_bet = (
                        math.isclose(float(existing["stake"]), stake, abs_tol=0.005)
                        and math.isclose(float(existing["placed_odds"] or existing["total_odds"]), effective_odds, abs_tol=0.005)
                        and self._business_legs(result["legs"]) == self._business_legs(legs)
                    )
                    if not same_bet:
                        raise ValueError("此 idempotency_key 已用於不同下注內容，請使用新的提交 key。")
                    result["ticket_id"] = result["id"]
                    return result
            if entry_mode == "recommendation":
                from .bet_validation import validate_recommendation_legs
                validate_recommendation_legs(legs)

            self.wallet.stake_bet(stake, ticket_id=ticket_id,
                                  notes=f"瘋狗流串關下注 ({len(legs)} 關, {effective_odds} 倍)", conn=conn)
            week_str = get_current_iso_week()
            conn.execute("""INSERT INTO tickets (id,created_at,week_str,status,stake,total_odds,
                recommendation_odds,placed_odds,potential_payout,actual_payout,sports_summary,legs_json,
                notes,entry_mode,idempotency_key)
                VALUES (?,?,?,'OPEN',?,?,?,?,?,0.0,?,?,?,?,?)""",
                (ticket_id, now_iso, week_str, stake, effective_odds, rec_odds, plc_odds,
                 potential_payout, sports_summary, legs_json, notes, entry_mode, idempotency_key))

        return {"ticket_id": ticket_id, "created_at": now_iso, "week_str": week_str,
                "status": "OPEN", "stake": stake, "total_odds": effective_odds,
                "recommendation_odds": rec_odds, "placed_odds": plc_odds,
                "potential_payout": potential_payout, "sports_summary": sports_summary,
                "legs": legs, "entry_mode": entry_mode, "idempotency_key": idempotency_key}

    def update_closing_odds(self, ticket_id: str, closing_odds: float) -> Optional[Dict[str, Any]]:
        try:
            closing_odds = float(closing_odds)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(closing_odds) or closing_odds <= 0:
            return None
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                return None
            ticket = self._ticket_dict(row)
            placed = ticket.get("placed_odds") or ticket["total_odds"]
            clv = round((placed / closing_odds) - 1.0, 4)
            conn.execute("UPDATE tickets SET closing_odds=?,clv=? WHERE id=?", (closing_odds, clv, ticket_id))
            ticket["closing_odds"], ticket["clv"] = closing_odds, clv
            return ticket

    def settle_ticket(self, ticket_id: str, won: bool, custom_payout: Optional[float] = None,
                      is_void: bool = False) -> Dict[str, Any]:
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                raise ValueError(f"找不到注單 ID: {ticket_id}")
            ticket = dict(row)
            if ticket["status"] != "OPEN":
                raise ValueError(f"注單已結算 (狀態: {ticket['status']})，不可重複結算。")
            if is_void:
                status, default_payout = "VOID", float(ticket["stake"])
            elif won:
                status, default_payout = "WON", float(ticket["potential_payout"])
            else:
                status, default_payout = "LOST", 0.0
            payout = default_payout if custom_payout is None else float(custom_payout)
            if not math.isfinite(payout) or payout < 0:
                raise ValueError("派彩金額必須是有限的非負數。")
            if status == "LOST" and payout != 0:
                raise ValueError("輸單不能有正派彩金額。")
            if status == "VOID" and not math.isclose(payout, float(ticket["stake"]), abs_tol=0.005):
                raise ValueError("VOID 只能按原注金退款；非原額派彩請使用 WON 並提供實際派彩金額。")
            payout = round(payout + 1e-10, 2)
            now_iso = get_now_iso()
            cursor = conn.execute("""UPDATE tickets SET status=?,actual_payout=?,settled_at=?
                WHERE id=? AND status='OPEN'""", (status, payout, now_iso, ticket_id))
            if cursor.rowcount != 1:
                raise ValueError("注單狀態已變更，無法重複結算。")
            if payout > 0:
                self.wallet.credit_winnings(payout, ticket_id=ticket_id,
                    notes=f"注單 #{ticket_id[:8]} ({status}) 派彩/退款 NT$ {payout:.2f} 入保留儲備池", conn=conn)
        return {"ticket_id": ticket_id, "won": won, "payout": payout, "status": status,
                "net_profit": round(payout - float(ticket["stake"]), 2)}

    def list_tickets(self, status_filter: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        query, params = "SELECT * FROM tickets", []
        if status_filter:
            query += " WHERE status=?"
            params.append(status_filter.upper())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        conn = self._get_connection()
        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            results = []
            for row in rows:
                item = self._ticket_dict(row)
                item["net_profit"] = round(item["actual_payout"] - item["stake"], 2) if item["status"] in ("WON", "LOST", "VOID") else 0.0
                results.append(item)
            return results
        finally:
            conn.close()

    def get_clv_analytics(self) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT clv FROM tickets WHERE clv IS NOT NULL").fetchall()
        finally:
            conn.close()
        if not rows:
            return {"sample_size": 0, "avg_clv_pct": 0.0, "beating_closing_line_rate": 0.0, "positive_clv_count": 0}
        vals = [float(r["clv"]) for r in rows]
        positives = sum(v > 0 for v in vals)
        return {"sample_size": len(vals), "avg_clv_pct": round(sum(vals) / len(vals) * 100.0, 2),
                "beating_closing_line_rate": round(positives / len(vals) * 100.0, 1), "positive_clv_count": positives}
