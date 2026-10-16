#!/usr/bin/env python3
"""Daily Ranked Parlay Snapshot Logger.

Records candidate parlay combinations across all multiplier tiers:
- 10-25x (穩健防守)
- 25-75x (狂犬推進)
- 75-200x (瘋狗進攻)
- 200-500x (極限 Moonshot)

Integrity Features:
1. Deterministic `parlay_fingerprint` (SHA-256 of sorted constituent legs)
2. Pairwise `leg_overlap_ratio` tracking
3. Official Taiwan Lottery Parlay VOID logic: A void leg becomes odds 1.0;
   parlay multiplier is recalculated and remains winning if other legs win.
4. Preserves 0-candidate tiers honestly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from core.experiment_identity import build_experiment_identity
from core.parlay_validation import freeze_candidate
from core.research_paths import research_paths
from core.persistence import append_jsonl, atomic_write_bytes, file_lock, read_jsonl

logger = logging.getLogger(__name__)

HISTORICAL_DIR = Path(__file__).resolve().parents[1] / "data" / "historical"
PARLAY_SNAPSHOT_FILE = research_paths()["parlays"]

MULTIPLIER_TIERS = [
    "10-25x",
    "25-75x",
    "75-200x",
    "200-500x",
]


def compute_parlay_fingerprint(legs: List[Any]) -> str:
    """Compute deterministic SHA-256 hash of sorted leg identifiers."""
    leg_keys = []
    for leg in legs:
        if hasattr(leg, "to_dict"):
            d = leg.to_dict()
        elif isinstance(leg, dict):
            d = leg
        else:
            d = {
                "event_id": getattr(leg, "event_id", ""),
                "market": getattr(leg, "market", ""),
                "selection": getattr(leg, "selection", ""),
                "line": getattr(leg, "line", ""),
            }
        key_tuple = (
            str(d.get("canonical_event_id") or ""),
            str(d.get("sport") or ""), str(d.get("league") or ""),
            str(d.get("start_time_utc") or d.get("event_start") or ""),
            str(d.get("event_id", "")),
            str(d.get("market", "")),
            str(d.get("selection", "")),
            str(d.get("line") if d.get("line") is not None else ""),
        )
        leg_keys.append(key_tuple)

    leg_keys.sort()
    repr_str = json.dumps(leg_keys, separators=(",", ":"))
    return hashlib.sha256(repr_str.encode("utf-8")).hexdigest()[:16]


def compute_leg_overlap_ratio(legs_a: List[Any], legs_b: List[Any]) -> float:
    """Compute Jaccard overlap ratio between two parlay leg sets."""
    def _to_set(legs: List[Any]) -> Set[str]:
        s = set()
        for l in legs:
            eid = l.get("event_id") if isinstance(l, dict) else getattr(l, "event_id", "")
            mkt = l.get("market") if isinstance(l, dict) else getattr(l, "market", "")
            sel = l.get("selection") if isinstance(l, dict) else getattr(l, "selection", "")
            s.add(f"{eid}:{mkt}:{sel}")
        return s

    set_a = _to_set(legs_a)
    set_b = _to_set(legs_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return round(intersection / float(union), 4) if union > 0 else 0.0


class ShadowParlayLogger:
    """Records and settles candidate parlay combinations across multiplier tiers."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or PARLAY_SNAPSHOT_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._strategy_metadata = get_strategy_metadata()

    def log_daily_parlays(self, *args, **kwargs):
        with file_lock(self.log_path):
            return self._log_daily_parlays_unlocked(*args, **kwargs)

    def _log_daily_parlays_unlocked(
        self,
        parlay_results_by_tier: Dict[str, Dict[str, List[Dict[str, Any]]]],
        date_str: Optional[str] = None,
        prediction_snapshots: Optional[List[Dict[str, Any]]] = None,
        run_window_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Record all parlay search results for today across tiers (append-only)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        date_key = date_str or now_iso[:10]
        recorded_entries = []
        snapshot_index = {s.get("snapshot_id"): s for s in prediction_snapshots or []}
        experiment_identity = build_experiment_identity(self._strategy_metadata)
        existing_by_tier = {}
        if run_window_id:
            for existing in self.get_all_parlay_snapshots():
                existing_identity = existing.get("experiment_identity") or (existing.get("strategy_metadata") or {}).get("experiment_identity")
                if (existing.get("run_window_id") == run_window_id
                        and existing_identity == experiment_identity):
                    existing_by_tier.setdefault(existing.get("multiplier_tier"), existing)

        for tier in MULTIPLIER_TIERS:
            if tier in existing_by_tier:
                recorded_entries.append(existing_by_tier[tier])
                continue
            tier_data = parlay_results_by_tier.get(tier, {})
            hc_list = tier_data.get("high_consensus", [])
            ag_list = tier_data.get("aggressive", [])
            ms_list = tier_data.get("moonshot", [])
            total_count = len(hc_list) + len(ag_list) + len(ms_list)

            entry_id = f"parlay_snap_{date_key}_{tier}_{uuid.uuid4().hex[:6]}"

            # Package candidate tickets
            candidates = []
            for target_type, items in [("HIGH", hc_list), ("AGGRESSIVE", ag_list), ("MOONSHOT", ms_list)]:
                for idx, item in enumerate(items):
                    ticket_legs = []
                    for leg in item.get("legs", []):
                        if hasattr(leg, "to_dict"):
                            leg_dict = leg.to_dict()
                        elif isinstance(leg, dict):
                            leg_dict = leg
                        else:
                            leg_dict = {
                                "event_id": str(getattr(leg, "event_id", "")),
                                "market": getattr(leg, "market", ""),
                                "selection": getattr(leg, "selection", ""),
                                "taiwan_odds": getattr(leg, "taiwan_odds", 1.0),
                                "line": getattr(leg, "line", None),
                            }
                        ticket_legs.append(leg_dict)

                    fp = compute_parlay_fingerprint(ticket_legs)

                    candidate = {
                        "candidate_id": f"{entry_id}_{target_type}_{idx}",
                        "parlay_fingerprint": fp,
                        "target_type": target_type,
                        "original_total_odds": float(item.get("total_odds", 1.0)),
                        "recalculated_total_odds": float(item.get("total_odds", 1.0)),
                        "legs_count": len(ticket_legs),
                        "legs": ticket_legs,
                        "bet_status": item.get("bet_status", "READY"),
                        "is_ready": item.get("is_ready", True),
                        "settled": False,
                        "settlement_status": "PENDING",
                        "won": None,
                        "actual_payout": 0.0,
                    }
                    freeze_candidate(candidate, item, snapshot_index, experiment_identity, now_iso, tier)
                    candidates.append(candidate)

            record = {
                "snapshot_id": entry_id,
                "date": date_key,
                "timestamp": now_iso,
                "multiplier_tier": tier,
                "high_consensus_count": len(hc_list),
                "aggressive_count": len(ag_list),
                "moonshot_count": len(ms_list),
                "total_candidate_count": total_count,
                "candidates": candidates,
                "strategy_version": STRATEGY_VERSION,
                "strategy_metadata": self._strategy_metadata,
                "experiment_identity": experiment_identity,
                "run_window_id": run_window_id,
                "run_id": run_id,
            }

            append_jsonl(self.log_path, record)
            recorded_entries.append(record)

        return recorded_entries

    def get_all_parlay_snapshots(self) -> List[Dict[str, Any]]:
        """Retrieve all recorded parlay snapshots."""
        return read_jsonl(self.log_path)

    def settle_parlay_candidate_with_taiwan_rules(self, *args, **kwargs):
        with file_lock(self.log_path):
            return self._settle_parlay_candidate_unlocked(*args, **kwargs)

    def _settle_parlay_candidate_unlocked(
        self,
        candidate_id: str,
        leg_statuses: List[Tuple[str, float]],  # List of (status, original_odds)
        virtual_stake: float = 10.0,
        leg_result_snapshots: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Settle a parlay candidate applying Taiwan Lottery VOID rules.

        If a leg is VOID or PUSH, that leg's multiplier becomes 1.0.
        If all non-void legs WON -> WON (payout = stake * recalculated_odds).
        If any leg is LOST -> LOST (payout = 0.0).
        If ALL legs are VOID/PUSH -> PUSH/VOID (payout = stake).
        """
        if not self.log_path.exists():
            return None

        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        updated_lines = []
        settled_candidate = None

        for line in lines:
            if not line.strip():
                continue
            data = json.loads(line)
            for c in data.get("candidates", []):
                if c.get("candidate_id") == candidate_id:
                    if c.get("settled"):
                        settled_candidate = c
                        continue
                    if len(leg_statuses) != len(c.get("legs", [])):
                        raise ValueError("Each ticket leg must have exactly one settlement result.")
                    if not isinstance(virtual_stake, (int, float)) or not math.isfinite(virtual_stake) or virtual_stake <= 0:
                        raise ValueError("Virtual stake must be finite and positive.")
                    for leg, (_, original_odds) in zip(c["legs"], leg_statuses):
                        if not math.isfinite(float(original_odds)) or float(original_odds) <= 1:
                            raise ValueError("Settlement requires finite original odds greater than one.")
                        if leg.get("taiwan_odds") is not None and not math.isclose(
                                float(leg["taiwan_odds"]), float(original_odds), abs_tol=1e-9):
                            raise ValueError("Settlement odds differ from the immutable ticket odds.")
                    # Calculate Taiwan rule multiplier
                    recalc_odds = 1.0
                    any_lost = False
                    all_void = True
                    has_win = False
                    has_pending = False

                    for status, orig_odds in leg_statuses:
                        if status == "LOST":
                            any_lost = True
                            all_void = False
                        elif status in ["VOID", "PUSH"]:
                            # Taiwan rule: void leg odds becomes 1.0!
                            recalc_odds *= 1.0
                        elif status == "WON":
                            recalc_odds *= orig_odds
                            all_void = False
                            has_win = True
                        else:
                            has_pending = True

                    recalc_odds = round(recalc_odds, 4)

                    if has_pending:
                        final_status = "PENDING"
                        won = None
                        payout = 0.0
                    elif any_lost:
                        final_status = "LOST"
                        won = False
                        payout = 0.0
                    elif all_void:
                        final_status = "VOID"
                        won = None
                        payout = virtual_stake
                    elif has_win:
                        final_status = "WON"
                        won = True
                        payout = round(virtual_stake * recalc_odds, 2)
                    else:
                        final_status = "PENDING"
                        won = None
                        payout = 0.0

                    c["settled"] = (final_status != "PENDING")
                    c["settlement_status"] = final_status
                    c["won"] = won
                    c["recalculated_total_odds"] = recalc_odds
                    c["actual_payout"] = payout
                    c["leg_settlement_statuses"] = list(leg_statuses)
                    c["leg_result_snapshots"] = leg_result_snapshots or []
                    c["profit_loss"] = round(payout - virtual_stake, 2) if final_status != "PENDING" else 0.0
                    c["settled_at"] = datetime.now(timezone.utc).isoformat()
                    settled_candidate = c

            updated_lines.append(json.dumps(data, ensure_ascii=False))

        if settled_candidate:
            atomic_write_bytes(self.log_path, ("\n".join(updated_lines) + "\n").encode("utf-8"))

        return settled_candidate
