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
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from core.experiment_identity import build_experiment_identity
from core.parlay_validation import freeze_candidate
from core.research_paths import research_paths
from core.persistence import append_jsonl, clear_jsonl_cache, file_lock, iter_jsonl, read_jsonl
from core.research_sqlite import (
    database_for_ledger,
    get_parlay_records_for_window,
    settle_parlays as settle_sqlite_parlays,
)

logger = logging.getLogger(__name__)

_RESEARCH_PATHS = research_paths()
HISTORICAL_DIR = _RESEARCH_PATHS["root"] / "historical"
PARLAY_SNAPSHOT_FILE = _RESEARCH_PATHS["parlays"]

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
            existing_records = get_parlay_records_for_window(self.log_path, run_window_id, experiment_identity)
            if existing_records is None:
                existing_records = iter_jsonl(self.log_path)
            for existing in existing_records:
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
        candidate_id = kwargs.get("candidate_id") or (args[0] if args else None)
        if candidate_id is None:
            raise TypeError("candidate_id is required")
        statuses = kwargs.get("leg_statuses", args[1] if len(args) > 1 else None)
        stake = kwargs.get("virtual_stake", args[2] if len(args) > 2 else 10.0)
        snapshots = kwargs.get("leg_result_snapshots", args[3] if len(args) > 3 else None)
        result = self.settle_parlay_candidates_with_taiwan_rules({
            str(candidate_id): {
                "leg_statuses": statuses,
                "virtual_stake": stake,
                "leg_result_snapshots": snapshots,
            }
        })
        return result.get(str(candidate_id))

    def settle_parlay_candidates_with_taiwan_rules(
        self, settlements: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Settle many candidates with one streaming ledger rewrite."""
        if not settlements:
            return {}

        if database_for_ledger(self.log_path):
            return settle_sqlite_parlays(self.log_path, settlements) or {}
        if not self.log_path.exists():
            return {}

        with file_lock(self.log_path):
            fd, temp_name = tempfile.mkstemp(prefix=".atomic-", suffix=".tmp", dir=self.log_path.parent)
            settled: Dict[str, Dict[str, Any]] = {}
            changed = False
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output, self.log_path.open("r", encoding="utf-8") as source:
                    for line in source:
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        for candidate in data.get("candidates", []):
                            candidate_id = str(candidate.get("candidate_id") or "")
                            request = settlements.get(candidate_id)
                            if not request:
                                continue
                            if candidate.get("settled"):
                                settled[candidate_id] = candidate
                                continue

                            leg_statuses = request.get("leg_statuses") or []
                            virtual_stake = request.get("virtual_stake", 10.0)
                            leg_result_snapshots = request.get("leg_result_snapshots") or []
                            if len(leg_statuses) != len(candidate.get("legs", [])):
                                raise ValueError("Each ticket leg must have exactly one settlement result.")
                            if not isinstance(virtual_stake, (int, float)) or not math.isfinite(virtual_stake) or virtual_stake <= 0:
                                raise ValueError("Virtual stake must be finite and positive.")
                            for leg, (_, original_odds) in zip(candidate["legs"], leg_statuses):
                                if not math.isfinite(float(original_odds)) or float(original_odds) <= 1:
                                    raise ValueError("Settlement requires finite original odds greater than one.")
                                if leg.get("taiwan_odds") is not None and not math.isclose(
                                    float(leg["taiwan_odds"]), float(original_odds), abs_tol=1e-9
                                ):
                                    raise ValueError("Settlement odds differ from the immutable ticket odds.")

                            recalculated_odds = 1.0
                            any_lost = False
                            all_void = True
                            has_win = False
                            has_pending = False
                            for status, original_odds in leg_statuses:
                                if status == "LOST":
                                    any_lost = True
                                    all_void = False
                                elif status in {"VOID", "PUSH"}:
                                    pass
                                elif status == "WON":
                                    recalculated_odds *= original_odds
                                    all_void = False
                                    has_win = True
                                else:
                                    has_pending = True
                            recalculated_odds = round(recalculated_odds, 4)

                            if has_pending:
                                status, won, payout = "PENDING", None, 0.0
                            elif any_lost:
                                status, won, payout = "LOST", False, 0.0
                            elif all_void:
                                status, won, payout = "VOID", None, virtual_stake
                            elif has_win:
                                status, won, payout = "WON", True, round(virtual_stake * recalculated_odds, 2)
                            else:
                                status, won, payout = "PENDING", None, 0.0

                            candidate["settled"] = status != "PENDING"
                            candidate["settlement_status"] = status
                            candidate["won"] = won
                            candidate["recalculated_total_odds"] = recalculated_odds
                            candidate["actual_payout"] = payout
                            candidate["leg_settlement_statuses"] = list(leg_statuses)
                            candidate["leg_result_snapshots"] = leg_result_snapshots
                            candidate["profit_loss"] = round(payout - virtual_stake, 2) if status != "PENDING" else 0.0
                            candidate["settled_at"] = datetime.now(timezone.utc).isoformat()
                            settled[candidate_id] = candidate
                            changed = True
                        output.write(json.dumps(data, ensure_ascii=False) + "\n")
                    output.flush()
                    os.fsync(output.fileno())

                if changed:
                    os.replace(temp_name, self.log_path)
                    clear_jsonl_cache(self.log_path)
                return settled
            finally:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
