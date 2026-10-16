#!/usr/bin/env python3
"""Ticket Manager for Sports Lottery Parlay Tracking and Settlement."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .war_chest import DEFAULT_DB_PATH, WarChestManager, get_current_week_str, get_now_iso


class TicketManager:
    def __init__(self, war_chest: Optional[WarChestManager] = None):
        self.war_chest = war_chest or WarChestManager()
        self.db_path = self.war_chest.db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def place_ticket(
        self,
        legs: List[Dict[str, Any]],
        stake: float,
        total_odds: float,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create and place a new parlay ticket. Deducts stake from War Chest."""
        if stake <= 0:
            raise ValueError("注金必須大於 0 元。")
        if not legs:
            raise ValueError("注單必須包含至少 1 個賽事關卡。")
        if total_odds <= 1.0:
            raise ValueError("總賠率必須大於 1.0。")

        stake = round(stake, 2)
        total_odds = round(total_odds, 2)
        potential_payout = round(stake * total_odds, 2)
        ticket_id = str(uuid.uuid4())
        now_iso = get_now_iso()
        week_str = get_current_week_str()

        # Deduct stake from War Chest (raises ValueError if balance insufficient)
        self.war_chest.commit_bet(
            stake=stake,
            ticket_id=ticket_id,
            notes=f"瘋狗流串關下注 ({len(legs)} 關, {total_odds:.2f} 倍)",
        )

        legs_json = json.dumps(legs, ensure_ascii=False)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tickets (
                    id, created_at, week_str, status, stake, total_odds,
                    potential_payout, actual_payout, legs_json, notes
                ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, 0.0, ?, ?)
                """,
                (
                    ticket_id,
                    now_iso,
                    week_str,
                    stake,
                    total_odds,
                    potential_payout,
                    legs_json,
                    notes,
                ),
            )
            conn.commit()

        return {
            "ticket_id": ticket_id,
            "created_at": now_iso,
            "week_str": week_str,
            "status": "OPEN",
            "stake": stake,
            "total_odds": total_odds,
            "potential_payout": potential_payout,
            "legs_count": len(legs),
            "legs": legs,
        }

    def settle_ticket(self, ticket_id: str, won: bool, custom_payout: Optional[float] = None) -> Dict[str, Any]:
        """Settle a ticket as WON or LOST. If WON, credits payout to War Chest."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if not row:
                raise ValueError(f"找不到注單 ID: {ticket_id}")
            ticket = dict(row)

        if ticket["status"] != "OPEN":
            raise ValueError(f"注單已結算過 (狀態: {ticket['status']})，不可重複結算。")

        payout = custom_payout if custom_payout is not None else (ticket["potential_payout"] if won else 0.0)
        settle_result = self.war_chest.settle_bet(
            ticket_id=ticket_id,
            won=won,
            payout=payout,
            notes="注單結算派彩" if won else "注單未過關",
        )

        return {
            "ticket_id": ticket_id,
            "won": won,
            "payout": payout,
            "status": "WON" if won else "LOST",
            "new_balance": settle_result["balance_after"],
        }

    def list_tickets(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List tickets, optionally filtered by status ('OPEN', 'WON', 'LOST')."""
        query = "SELECT * FROM tickets"
        params: List[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status.upper())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                try:
                    d["legs"] = json.loads(d.get("legs_json", "[]"))
                except Exception:
                    d["legs"] = []
                results.append(d)
            return results
