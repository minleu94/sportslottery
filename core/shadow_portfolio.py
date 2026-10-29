#!/usr/bin/env python3
"""Shadow Portfolio Manager.

Simulates automated paper betting on top parlay candidates using fixed virtual stakes (NT$10).
Runs entirely isolated in `data/shadow/shadow_portfolio.sqlite` to objectively evaluate
strategy performance without affecting the real Weekly NT$200 Wallet.

Integrity Rules Enforced:
1. Shadow Bet Identity: `parlay_fingerprint` deterministic SHA-256
2. Duplicate Protection: If TOP_HIGH, TOP_MED, or TOP_TARGET produce identical fingerprints,
   only ONE ticket is wagered with combined strategy_tags (N = 1, virtual stake = NT$10, not NT$30).
3. Daily Idempotency: Re-running on the same date will not duplicate identical wagers.
4. Comprehensive Statuses: WON, LOST, PUSH, VOID, PENDING.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.shadow_parlay_logger import compute_parlay_fingerprint
from core.strategy_version import GOVERNANCE_RULES, STRATEGY_VERSION
from core.experiment_identity import get_current_experiment_identity, validate_experiment_identity
from core.research_paths import research_paths
from core.snapshot_logger import compute_prediction_payload_hash

logger = logging.getLogger(__name__)

SHADOW_DIR = Path(__file__).resolve().parents[1] / "data" / "shadow"
SHADOW_DB_PATH = SHADOW_DIR / "shadow_portfolio.sqlite"
VIRTUAL_STAKE = GOVERNANCE_RULES["virtual_shadow_stake_ntd"]  # NT$10.0
DEFAULT_SNAPSHOT_PATH = research_paths()["snapshots"]


def compute_ticket_payload_hash(ticket: Dict[str, Any]) -> str:
    payload = {key: ticket.get(key) for key in (
        "parlay_fingerprint", "date", "strategy_version", "experiment_id",
        "experiment_identity", "selection_category", "multiplier_tier", "total_odds",
        "virtual_stake", "potential_payout", "legs", "leg_snapshot_refs",
        "forward_validation_eligible",
    )}
    import hashlib
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ShadowPortfolioManager:
    """Manages virtual shadow bets for forward performance evaluation."""

    def __init__(self, db_path: Optional[Path] = None, snapshot_path: Optional[Path] = None):
        self.db_path = db_path or SHADOW_DB_PATH
        self.snapshot_path = Path(snapshot_path or DEFAULT_SNAPSHOT_PATH)
        self.experiment_identity = get_current_experiment_identity()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_tickets (
                    id TEXT PRIMARY KEY,
                    parlay_fingerprint TEXT NOT NULL DEFAULT '',
                    placed_at TEXT NOT NULL,
                    date TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    experiment_id TEXT,
                    experiment_identity_json TEXT NOT NULL DEFAULT '',
                    leg_snapshot_refs_json TEXT NOT NULL DEFAULT '[]',
                    forward_validation_eligible INTEGER NOT NULL DEFAULT 0,
                    ticket_payload_hash TEXT NOT NULL DEFAULT '',
                    selection_category TEXT NOT NULL,
                    strategy_tags TEXT NOT NULL DEFAULT '',
                    multiplier_tier TEXT NOT NULL,
                    total_odds REAL NOT NULL,
                    virtual_stake REAL NOT NULL,
                    potential_payout REAL NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('OPEN', 'WON', 'LOST', 'PUSH', 'VOID')),
                    actual_payout REAL NOT NULL DEFAULT 0.0,
                    net_profit REAL NOT NULL DEFAULT 0.0,
                    settled_at TEXT,
                    legs_json TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                );
                """
            )
            # Add columns if missing from earlier migration
            try:
                conn.execute("ALTER TABLE shadow_tickets ADD COLUMN parlay_fingerprint TEXT NOT NULL DEFAULT '';")
            except Exception:
                pass

            for column, declaration in (
                ("experiment_id", "TEXT"),
                ("experiment_identity_json", "TEXT NOT NULL DEFAULT ''"),
                ("leg_snapshot_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("forward_validation_eligible", "INTEGER NOT NULL DEFAULT 0"),
                ("ticket_payload_hash", "TEXT NOT NULL DEFAULT ''"),
            ):
                try:
                    conn.execute(f"ALTER TABLE shadow_tickets ADD COLUMN {column} {declaration}")
                except sqlite3.OperationalError:
                    pass
            try:
                conn.execute("ALTER TABLE shadow_tickets ADD COLUMN strategy_tags TEXT NOT NULL DEFAULT '';")
            except Exception:
                pass

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_tickets_status ON shadow_tickets(status);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_tickets_fp_date ON shadow_tickets(parlay_fingerprint, date);
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_shadow_tickets_exp_fp_date "
                "ON shadow_tickets(experiment_id, parlay_fingerprint, date)"
            )
            conn.commit()

    def _snapshot_index(self) -> Dict[str, Dict[str, Any]]:
        if not self.snapshot_path.exists():
            return {}
        rows = []
        for line in self.snapshot_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except (TypeError, ValueError):
                continue
        return {str(row.get("snapshot_id")): row for row in rows if row.get("snapshot_id")}

    @staticmethod
    def _leg_snapshot_ref(leg: Dict[str, Any], snapshots: Dict[str, Dict[str, Any]],
                          identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        evidence = leg.get("signal_evidence") or {}
        snapshot_id = evidence.get("snapshot_id")
        snapshot = snapshots.get(str(snapshot_id)) if snapshot_id else None
        if not isinstance(snapshot, dict):
            return None
        if (snapshot.get("experiment_identity") != identity
                or (snapshot.get("strategy_metadata") or {}).get("experiment_identity") != identity
                or snapshot.get("strategy_config_hashes") != identity.get("config_hashes")
                or snapshot.get("forward_validation_eligible") is not True
                or snapshot.get("prediction_payload_hash") != compute_prediction_payload_hash(snapshot)):
            return None
        field_map = {"event_id": "event_id", "canonical_event_id": "canonical_event_id",
                     "sport": "sport", "league": "league", "market": "market",
                     "selection": "selection", "side": "side", "line": "line"}
        for leg_key, snapshot_key in field_map.items():
            if leg.get(leg_key) is not None and leg.get(leg_key) != snapshot.get(snapshot_key):
                return None
        if leg.get("odds_scraped_at") != snapshot.get("odds_timestamp"):
            return None
        leg_odds = leg.get("taiwan_odds")
        snapshot_odds = snapshot.get("taiwan_odds")
        try:
            if not math.isclose(float(leg_odds), float(snapshot_odds), rel_tol=0, abs_tol=1e-9):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        return {"snapshot_id": str(snapshot_id),
                "prediction_payload_hash": snapshot["prediction_payload_hash"],
                "experiment_id": identity["experiment_id"]}

    def _ticket_is_current_and_sealed(self, row: Dict[str, Any], snapshots: Dict[str, Dict[str, Any]],
                                      experiment_id: str) -> bool:
        try:
            identity = json.loads(row.get("experiment_identity_json") or "")
            legs = json.loads(row.get("legs_json") or "[]")
            refs = json.loads(row.get("leg_snapshot_refs_json") or "[]")
            ticket = {**row, "experiment_identity": identity, "legs": legs,
                      "leg_snapshot_refs": refs,
                      "forward_validation_eligible": bool(row.get("forward_validation_eligible"))}
            if (identity.get("experiment_id") != experiment_id
                    or row.get("experiment_id") != experiment_id
                    or not validate_experiment_identity(identity)
                    or row.get("strategy_version") != identity.get("strategy_version")
                    or row.get("ticket_payload_hash") != compute_ticket_payload_hash(ticket)
                    or not ticket["forward_validation_eligible"]
                    or not legs or len(legs) != len(refs)):
                return False
            for leg, ref in zip(legs, refs):
                if self._leg_snapshot_ref(leg, snapshots, identity) != ref:
                    return False
            return True
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            return False

    def place_shadow_ticket(
        self,
        legs: List[Dict[str, Any]],
        total_odds: float,
        selection_category: str,
        multiplier_tier: str,
        strategy_tags: Optional[List[str]] = None,
        date_str: Optional[str] = None,
        notes: str = "",
        experiment_identity: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Place an isolated paper bet with fixed NT$10 virtual stake (deduplicated)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        date_key = date_str or now_iso[:10]
        total_odds = round(float(total_odds), 2)
        if not math.isfinite(total_odds) or total_odds <= 1:
            raise ValueError("影子注單賠率必須大於 1 且為有限值。")
        stake = float(VIRTUAL_STAKE)
        potential = round(stake * total_odds, 2)

        legs_clean = []
        for l in legs:
            if hasattr(l, "to_dict"):
                legs_clean.append(l.to_dict())
            elif isinstance(l, dict):
                legs_clean.append(l)
            else:
                legs_clean.append({
                    "event_id": str(getattr(l, "event_id", "")),
                    "market": getattr(l, "market", ""),
                    "selection": getattr(l, "selection", ""),
                    "taiwan_odds": getattr(l, "taiwan_odds", 1.0),
                    "line": getattr(l, "line", None),
                })

        fp = compute_parlay_fingerprint(legs_clean)
        identity = experiment_identity or self.experiment_identity
        if not validate_experiment_identity(identity):
            raise ValueError("Shadow tickets require a valid experiment identity.")
        snapshot_index = self._snapshot_index()
        snapshot_refs = [self._leg_snapshot_ref(leg, snapshot_index, identity) for leg in legs_clean]
        forward_eligible = bool(legs_clean and all(snapshot_refs))
        ticket_payload = {
            "parlay_fingerprint": fp,
            "date": date_key,
            "strategy_version": identity["strategy_version"],
            "experiment_id": identity["experiment_id"],
            "experiment_identity": identity,
            "selection_category": selection_category,
            "multiplier_tier": multiplier_tier,
            "total_odds": total_odds,
            "virtual_stake": stake,
            "potential_payout": potential,
            "legs": legs_clean,
            "leg_snapshot_refs": snapshot_refs,
            "forward_validation_eligible": forward_eligible,
        }
        ticket_payload_hash = compute_ticket_payload_hash(ticket_payload)
        tags_list = strategy_tags or [selection_category]
        tags_str = json.dumps(tags_list, ensure_ascii=False)

        # Idempotency / Deduplication check: check if identical wager placed on this date
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "SELECT * FROM shadow_tickets WHERE parlay_fingerprint = ? AND date = ? AND experiment_id = ?",
                (fp, date_key, identity["experiment_id"]),
            )
            existing = cur.fetchone()
            if existing:
                # Merge strategy tag into existing ticket without deducting additional stake!
                existing_tags = []
                try:
                    existing_tags = json.loads(existing["strategy_tags"]) if existing["strategy_tags"] else [existing["selection_category"]]
                except Exception:
                    existing_tags = [existing["selection_category"]]

                merged_tags = list(set(existing_tags + tags_list))
                conn.execute(
                    "UPDATE shadow_tickets SET strategy_tags = ? WHERE id = ?",
                    (json.dumps(merged_tags, ensure_ascii=False), existing["id"]),
                )
                conn.commit()
                return {
                    "ticket_id": existing["id"],
                    "placed_at": existing["placed_at"],
                    "category": existing["selection_category"],
                    "strategy_tags": merged_tags,
                    "total_odds": existing["total_odds"],
                    "virtual_stake": existing["virtual_stake"],
                    "potential_payout": existing["potential_payout"],
                    "deduplicated": True,
                }

            ticket_id = f"shadow_{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO shadow_tickets (
                    id, parlay_fingerprint, placed_at, date, strategy_version, selection_category,
                    experiment_id, experiment_identity_json, leg_snapshot_refs_json,
                    forward_validation_eligible, ticket_payload_hash,
                    strategy_tags, multiplier_tier, total_odds, virtual_stake, potential_payout,
                    status, actual_payout, net_profit, legs_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 0.0, 0.0, ?, ?)
                """,
                (
                    ticket_id,
                    fp,
                    now_iso,
                    date_key,
                    identity["strategy_version"],
                    selection_category,
                    identity["experiment_id"],
                    json.dumps(identity, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot_refs, ensure_ascii=False, sort_keys=True),
                    int(forward_eligible),
                    ticket_payload_hash,
                    tags_str,
                    multiplier_tier,
                    total_odds,
                    stake,
                    potential,
                    json.dumps(legs_clean, ensure_ascii=False),
                    notes,
                ),
            )
            conn.commit()

        return {
            "ticket_id": ticket_id,
            "parlay_fingerprint": fp,
            "experiment_id": identity["experiment_id"],
            "experiment_identity": identity,
            "forward_validation_eligible": forward_eligible,
            "placed_at": now_iso,
            "category": selection_category,
            "strategy_tags": tags_list,
            "total_odds": total_odds,
            "virtual_stake": stake,
            "potential_payout": potential,
            "deduplicated": False,
        }

    def place_daily_top_picks(
        self,
        parlay_results: Dict[str, Dict[str, List[Dict[str, Any]]]],
        date_str: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Pick and record today's Top HIGH, Top MED, and Top Target candidates with strict deduplication."""
        placed = []
        candidates_to_eval = []

        # 1. Top HIGH
        high_pool = (
            parlay_results.get("10-25x", {}).get("high_consensus", []) +
            parlay_results.get("25-75x", {}).get("high_consensus", [])
        )
        if high_pool:
            candidates_to_eval.append(("TOP_HIGH", high_pool[0]))

        # 2. Top MED
        med_pool = (
            parlay_results.get("10-25x", {}).get("aggressive", []) +
            parlay_results.get("25-75x", {}).get("aggressive", [])
        )
        if med_pool:
            candidates_to_eval.append(("TOP_MED", med_pool[0]))

        # 3. Top Target
        target_pool = (
            parlay_results.get("25-75x", {}).get("moonshot", []) +
            parlay_results.get("75-200x", {}).get("moonshot", []) +
            parlay_results.get("10-25x", {}).get("moonshot", [])
        )
        if target_pool:
            candidates_to_eval.append(("TOP_TARGET", target_pool[0]))

        # Group by fingerprint to deduplicate identical bets across tags
        grouped_by_fp: Dict[str, Dict[str, Any]] = {}
        for cat, item in candidates_to_eval:
            legs = item.get("legs", [])
            fp = compute_parlay_fingerprint(legs)
            if fp not in grouped_by_fp:
                grouped_by_fp[fp] = {
                    "primary_cat": cat,
                    "tags": [cat],
                    "item": item,
                }
            else:
                grouped_by_fp[fp]["tags"].append(cat)

        # Place each unique wager once
        for fp, group in grouped_by_fp.items():
            item = group["item"]
            t = self.place_shadow_ticket(
                legs=item.get("legs", []),
                total_odds=item.get("total_odds", 10.0),
                selection_category=group["primary_cat"],
                multiplier_tier=item.get("multiplier_tier", "10-25x"),
                strategy_tags=group["tags"],
                date_str=date_str,
                notes=f"每日組合 (Tags: {', '.join(group['tags'])})",
            )
            placed.append(t)

        return placed

    def settle_ticket(
        self,
        ticket_id: str,
        won: Optional[bool] = None,
        settlement_status: Optional[str] = None,
        recalculated_odds: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Settle a shadow ticket supporting Taiwan rules (WON, LOST, PUSH, VOID)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT * FROM shadow_tickets WHERE id = ?", (ticket_id,))
            row = cur.fetchone()
            if not row:
                return None
            if row["status"] != "OPEN":
                return dict(row)

            stake = float(row["virtual_stake"])
            eff_odds = recalculated_odds if recalculated_odds is not None else float(row["total_odds"])

            # Resolve status
            if settlement_status is not None:
                status = settlement_status.upper()
            elif won is not None:
                status = "WON" if won else "LOST"
            else:
                raise ValueError("尚未確定結果，不可把影子注單預設為輸單。")
            if status not in {"WON", "LOST", "VOID", "PUSH"}:
                raise ValueError("未明確結算的影子注單保持 OPEN。")
            if not math.isfinite(float(eff_odds)) or float(eff_odds) < 1:
                raise ValueError("結算倍率必須是至少 1 的有限值。")

            if status == "WON":
                actual_payout = round(stake * eff_odds, 2)
                net_profit = round(actual_payout - stake, 2)
            elif status in ["VOID", "PUSH"]:
                status = settlement_status or "VOID"
                # Taiwan lottery void/push refund rule: payout = stake, net_profit = 0
                actual_payout = stake
                net_profit = 0.0
            else:
                status = "LOST"
                actual_payout = 0.0
                net_profit = -stake

            conn.execute(
                """
                UPDATE shadow_tickets
                SET status = ?, actual_payout = ?, net_profit = ?, settled_at = ?
                WHERE id = ?
                """,
                (status, actual_payout, net_profit, now_iso, ticket_id),
            )
            conn.commit()

            return {
                "id": ticket_id,
                "status": status,
                "actual_payout": actual_payout,
                "net_profit": net_profit,
                "settled_at": now_iso,
            }

    def get_portfolio_summary(self, strategy_version: Optional[str] = None, eligible_only: bool = False,
                              experiment_id: Optional[str] = None) -> Dict[str, Any]:
        """Compute virtual cumulative stake, payout, P/L, unique tickets, and overlap."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM shadow_tickets")
            rows = [dict(r) for r in cur.fetchall()]
        all_count = len(rows)
        target_experiment_id = (
            self.experiment_identity.get("experiment_id") if eligible_only else experiment_id
        )
        if strategy_version:
            rows = [row for row in rows if row.get("strategy_version") == strategy_version]
        if target_experiment_id:
            rows = [row for row in rows if row.get("experiment_id") == target_experiment_id]
        if eligible_only:
            snapshot_index = self._snapshot_index()
            rows = [row for row in rows if self._ticket_is_current_and_sealed(
                row, snapshot_index, target_experiment_id or self.experiment_identity["experiment_id"]
            )]

        total_tickets = len(rows)
        settled_rows = [r for r in rows if r["status"] in ["WON", "LOST", "VOID", "PUSH"]]
        settled_count = len(settled_rows)
        won_count = sum(1 for r in settled_rows if r["status"] == "WON")

        total_stake = sum(r["virtual_stake"] for r in settled_rows)
        total_payout = sum(r["actual_payout"] for r in settled_rows)
        net_pl = round(total_payout - total_stake, 2)
        roi_pct = round((net_pl / total_stake) * 100.0, 2) if total_stake > 0 else 0.0

        # Unique fingerprints count
        unique_fps = len(set(r["parlay_fingerprint"] for r in rows if r.get("parlay_fingerprint")))

        is_insufficient_sample = settled_count < GOVERNANCE_RULES["insufficient_sample_threshold"]

        return {
            "total_tickets_logged": total_tickets,
            "unique_parlays_count": unique_fps,
            "settled_tickets": settled_count,
            "open_tickets": total_tickets - settled_count,
            "wins": won_count,
            "win_rate": round(won_count / settled_count, 4) if settled_count > 0 else 0.0,
            "total_virtual_staked": total_stake,
            "total_virtual_payout": total_payout,
            "net_pl": net_pl,
            "roi_pct": roi_pct,
            "is_insufficient_sample": is_insufficient_sample,
            "strategy_version": STRATEGY_VERSION,
            "experiment_id": target_experiment_id or self.experiment_identity.get("experiment_id"),
            "excluded_tickets": all_count - len(rows),
            "eligible_only": eligible_only,
        }

    def get_recent_tickets(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent shadow tickets."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM shadow_tickets ORDER BY placed_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
