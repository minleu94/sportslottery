#!/usr/bin/env python3
"""Historical Prediction Snapshot Logger.

Persists every TaiwanLeg prediction evaluation into `data/historical/prediction_snapshots.jsonl`
(append-only) to support shadow evaluation, calibration audits, Brier score, and log loss tracking.
Records are sealed under the active strategy version with deterministic payload hashes.

Integrity Gates Enforced:
1. Pre-Game Cutoff Integrity: snapshot_timestamp < event_start_time
2. Deterministic Prediction Payload Hash (SHA-256)
3. Audit Failure Protection: Settlement raises AuditFailureError if original payload is altered
4. Daily Snapshot Idempotency: Duplicate predictions on the same day are rejected
5. Audit Lineage & Exclusion Tracking: Non-eligible predictions carry explicit exclusion_reason.
"""

from __future__ import annotations

import hashlib
import json
import copy
import logging
import math
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.settlement.taiwan_rules import resolve_settlement_rule_id
from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from core.research_paths import research_paths
from core.experiment_identity import get_current_experiment_identity
from core.persistence import read_jsonl, append_jsonl, atomic_write_bytes, file_lock
from integrations.common.models import TaiwanLeg

logger = logging.getLogger(__name__)

HISTORICAL_DIR = Path(__file__).resolve().parents[1] / "data" / "historical"
SNAPSHOT_FILE = research_paths()["snapshots"]


class AuditFailureError(Exception):
    """Raised when an existing prediction payload has been modified or corrupted."""
    pass


def compute_prediction_payload_hash(record: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of all original pre-game prediction fields."""
    canonical_keys = [
        "snapshot_timestamp",
        "event_id",
        "event_start",
        "sport",
        "league",
        "away_team",
        "home_team",
        "market",
        "selection",
        "side",
        "line",
        "taiwan_odds",
        "odds_timestamp",
        "market_implied_prob",
        "crowd_ratio",
        "crowd_votes",
        "model_probability",
        "model_market_delta_pp",
        "evidence_quality",
        "strategy_version",
        "settlement_rule_id",
    ]
    canonical = {k: record.get(k) for k in canonical_keys}
    # Additive identity metadata is hash-covered when present, while old records
    # without the field keep their original digest contract.
    if record.get("source_game_id") is not None:
        canonical["source_game_id"] = record["source_game_id"]
    if int(record.get("prediction_hash_schema", 1) or 1) >= 2:
        for key in (
            "canonical_event_id", "probability_status", "probability_source",
            "model_probability_raw", "model_probability_calibrated", "model_provenances", "model_as_of",
            "publication_time_precision", "expert_observed_at", "verified_experts", "signals",
            "model_predictions", "crowd_ratio", "crowd_votes",
        ):
            canonical[key] = record.get(key)
    if int(record.get("prediction_hash_schema", 1) or 1) >= 3:
        # Version 3 expands the digest without changing historical schema-2 hashes.
        for key in (
            "forward_validation_eligible", "exclusion_reason", "expected_value",
            "consensus_probability", "market_fair_probability", "market_fair_method",
            "market_evidence", "signal_evidence", "model_fusion_groups",
            "excluded_model_ids", "expert_observed_at", "strategy_metadata",
            "strategy_config_hashes", "freshness",
        ):
            if key in record:
                canonical[key] = record.get(key)
    if int(record.get("prediction_hash_schema", 1) or 1) >= 4:
        for key in ("experiment_identity", "observation_window_id", "model_candidate_predictions", "recommendation_probability",
                    "model_candidate_probability_raw", "model_candidate_probability_fused",
                    "model_candidate_provenances", "model_acceptance_statuses"):
            if key in record:
                canonical[key] = record.get(key)
    payload_str = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


def check_cutoff_integrity(
    snapshot_timestamp_iso: str,
    event_start_iso: Optional[str],
    odds_timestamp_iso: Optional[str] = None,
    expert_precision: str = "UNKNOWN",
    model_as_of_iso: Optional[str] = None,
    expert_timestamp_iso: Any = None,
) -> Tuple[bool, Optional[str]]:
    """Verify that prediction and evidence strictly precede the event start time.

    Returns (is_eligible, exclusion_reason).
    """
    if not event_start_iso:
        return False, "START_TIME_UNKNOWN"
    if expert_precision != "NOT_APPLICABLE" and expert_precision not in {"DATETIME", "TIMESTAMP", "SECOND"}:
        return False, "EXPERT_TIME_UNKNOWN"
    if not odds_timestamp_iso:
        return False, "ODDS_TIME_UNKNOWN"

    try:
        # Standardize ISO timestamps and require timezone-aware observations.
        snap_dt = datetime.fromisoformat(snapshot_timestamp_iso.replace("Z", "+00:00"))
        start_dt = datetime.fromisoformat(event_start_iso.replace("Z", "+00:00"))
        if snap_dt.tzinfo is None or start_dt.tzinfo is None:
            return False, "TIME_UNKNOWN"
        odds_dt = datetime.fromisoformat(odds_timestamp_iso.replace("Z", "+00:00"))
        if odds_dt.tzinfo is None:
            return False, "ODDS_TIME_UNKNOWN"
        if odds_dt > snap_dt:
            return False, "ODDS_AFTER_SNAPSHOT"
        if (snap_dt - odds_dt).total_seconds() > 15 * 60:
            return False, "ODDS_STALE"
        # 1. Prediction and odds observations must strictly precede event start.
        if snap_dt >= start_dt or odds_dt >= start_dt:
            return False, "POST_START_DATA"
        if expert_precision != "NOT_APPLICABLE":
            expert_times = expert_timestamp_iso if isinstance(expert_timestamp_iso, (list, tuple)) else [expert_timestamp_iso]
            expert_times = [value for value in expert_times if value]
            if not expert_times:
                return False, "EXPERT_TIME_UNKNOWN"
            for value in expert_times:
                expert_dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if expert_dt.tzinfo is None:
                    return False, "EXPERT_TIME_UNKNOWN"
                if expert_dt >= snap_dt or expert_dt >= start_dt:
                    return False, "POST_START_EXPERT_DATA"
        if model_as_of_iso:
            model_dt = datetime.fromisoformat(model_as_of_iso.replace("Z", "+00:00"))
            if model_dt.tzinfo is None:
                return False, "MODEL_TIME_UNKNOWN"
            if model_dt > snap_dt or model_dt >= start_dt:
                return False, "POST_START_MODEL_DATA"
    except Exception as exc:
        logger.debug("Failed parsing timestamp for cutoff check: %s", exc)
        return False, "TIME_INVALID"
    return True, None


class PredictionSnapshotLogger:
    """Records and settles immutable historical prediction snapshots."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or SNAPSHOT_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._strategy_metadata = get_strategy_metadata()
        self._experiment_identity = get_current_experiment_identity()

    @contextmanager
    def _file_lock(self):
        """Serialize append and replace operations across threads and processes."""
        with file_lock(self.log_path):
            yield

    def log_snapshot(self, leg: TaiwanLeg, observation_window_id: Optional[str] = None) -> Dict[str, Any]:
        """Record an evaluation snapshot for a TaiwanLeg (append-only & idempotent)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        date_key = now_iso[:10]
        event_start = getattr(leg, "start_time_utc", None) or getattr(leg, "start_time", None)

        # Seal an independent copy at the point of recording. Callers often add
        # the returned snapshot_id to the leg's evidence after logging; shared
        # nested dictionaries would otherwise mutate the in-memory sealed row.
        evidence = copy.deepcopy(leg.signal_evidence or {})

        def finite_probability(value):
            try:
                number = float(value)
                return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None
            except (TypeError, ValueError, OverflowError):
                return None

        try:
            odds_value = float(leg.taiwan_odds)
            odds_valid = math.isfinite(odds_value) and odds_value > 1.0
        except (TypeError, ValueError, OverflowError):
            odds_value, odds_valid = None, False
        market_implied = 1.0 / odds_value if odds_valid else None

        # Extract crowd metrics
        crowd_ratio = evidence.get("crowd_ratio", evidence.get("consensus_ratio"))
        crowd_votes = evidence.get("crowd_votes", evidence.get("vote_count"))
        crowd_age = evidence.get("crowd_age_minutes")

        # Extract verified expert metrics
        experts = evidence.get("verified_experts", [])
        expert_consensus = evidence.get("expert_consensus", evidence.get("expert_count", len(experts)))
        expert_precision = evidence.get("publication_time_precision")
        if not experts and not evidence.get("expert_count"):
            expert_precision = "NOT_APPLICABLE"
        elif not expert_precision:
            expert_precision = "UNKNOWN"

        # Only explicitly fused model groups count as model provenance. Signal
        # generation timestamps are not data-as-of timestamps.
        model_categories = {"OPEN_SOURCE_ENGINE", "EXTERNAL_OPEN_SOURCE_ENGINE", "LOCAL_REIMPLEMENTATION", "LOCAL_FALLBACK_MODEL", "MODEL"}
        probability_status = evidence.get("probability_status") or "MARKET_BASELINE_ONLY"
        model_statuses = {"UNVALIDATED_MODEL_ESTIMATE", "MODEL_ESTIMATE", "CALIBRATED_MODEL_ESTIMATE"}
        has_model_estimate = probability_status in model_statuses
        fusion_groups = evidence.get("model_fusion_groups")
        fusion_groups = list(fusion_groups) if isinstance(fusion_groups, (list, tuple, set)) else []
        excluded_model_ids = evidence.get("excluded_model_ids")
        excluded_model_ids = list(excluded_model_ids) if isinstance(excluded_model_ids, (list, tuple, set)) else []

        def signal_dict(signal):
            return signal.to_dict() if hasattr(signal, "to_dict") else signal

        candidates_by_group = {}
        if has_model_estimate and fusion_groups:
            for signal in getattr(leg, "signals", []):
                item = signal_dict(signal)
                if not isinstance(item, dict) or item.get("source_category") not in model_categories:
                    continue
                group = item.get("independence_group") or item.get("source_id")
                metadata = item.get("metadata") or {}
                if (group in fusion_groups and item.get("source_id") not in excluded_model_ids
                        and item.get("freshness_status") in {"LIVE", "FRESH", "AGING"}
                        and metadata.get("initialized") is not False
                        and finite_probability(item.get("probability")) is not None):
                    candidates_by_group.setdefault(group, []).append(item)
        # Edge evaluation selects one deterministic source per lineage.
        adopted_signals = [
            sorted(rows, key=lambda item: str(item.get("source_id") or ""))[0]
            for group, rows in candidates_by_group.items() if group in fusion_groups
        ]

        model_provenances = evidence.get("model_provenances")
        if not isinstance(model_provenances, list):
            model_provenances = []
        adopted_ids = {item.get("source_id") for item in adopted_signals}
        adopted_groups = {item.get("independence_group") or item.get("source_id") for item in adopted_signals}
        if adopted_signals:
            model_provenances = [item for item in model_provenances if isinstance(item, dict) and (
                item.get("source_id") in adopted_ids
                or (item.get("independence_group") or item.get("group")) in adopted_groups
            )] or adopted_signals
        else:
            model_provenances = []
        model_predictions: Dict[str, float] = {
            item.get("source_name", "model"): round(finite_probability(item.get("probability")), 4)
            for item in adopted_signals
        }

        model_prob = finite_probability(evidence.get("consensus_probability")) if has_model_estimate else None
        model_probability_invalid = has_model_estimate and model_prob is None

        delta_pp = evidence.get("model_market_delta_pp")
        if delta_pp is None and model_prob is not None and market_implied is not None:
            delta_pp = round((model_prob - market_implied) * 100.0, 2)

        # Resolve official Taiwan settlement rule ID
        rule_id = resolve_settlement_rule_id(leg.sport, leg.league, leg.market)

        # Pre-game Cutoff Integrity Check
        odds_scraped_at = getattr(leg, "odds_scraped_at", None)
        model_times = [item.get("data_as_of") for item in adopted_signals if item.get("data_as_of")]
        try:
            parsed_model_times = [datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in model_times]
            if any(value.tzinfo is None for value in parsed_model_times):
                model_as_of = "UNKNOWN"
            else:
                model_as_of = max(parsed_model_times).isoformat() if parsed_model_times else None
        except (TypeError, ValueError):
            model_as_of = "INVALID"
        if has_model_estimate and not adopted_signals:
            exclusion_reason = "MODEL_EVIDENCE_UNKNOWN"
            is_eligible = False
        elif has_model_estimate and (model_probability_invalid or any(
                finite_probability(evidence.get(key)) is None
                for key in ("model_probability_raw", "model_probability_calibrated")
                if evidence.get(key) is not None)):
            exclusion_reason = "MODEL_PROBABILITY_INVALID"
            is_eligible = False
        elif has_model_estimate and (
                not model_times
                or any(not item.get("data_as_of") for item in adopted_signals)
                or model_as_of in {"UNKNOWN", "INVALID"}):
            exclusion_reason = "MODEL_TIME_UNKNOWN"
            is_eligible = False
        elif has_model_estimate and model_as_of == "UNKNOWN":
            exclusion_reason = "MODEL_TIME_UNKNOWN"
            is_eligible = False
        else:
            is_eligible, exclusion_reason = check_cutoff_integrity(
            snapshot_timestamp_iso=now_iso,
            event_start_iso=event_start,
            odds_timestamp_iso=odds_scraped_at,
            expert_precision=expert_precision,
            model_as_of_iso=model_as_of,
            expert_timestamp_iso=evidence.get("expert_publication_timestamp") or [
                expert.get("pick_timestamp") for expert in experts
                if isinstance(expert, dict) and expert.get("pick_timestamp")
            ],
            )
        odds_status = getattr(leg, "odds_status", "UNKNOWN")
        if odds_status not in {"LIVE", "FRESH"}:
            is_eligible = False
            exclusion_reason = "ODDS_STALE" if odds_status == "STALE_CACHE" else "ODDS_STATUS_UNKNOWN"
        if not odds_valid:
            is_eligible = False
            exclusion_reason = "ODDS_INVALID"

        # Idempotency Check: strategy_version + event_id + market + selection + date
        event_identity = getattr(leg, "canonical_event_id", None) or evidence.get("source_game_id") or f"{leg.event_id}:{event_start or 'TIME_UNKNOWN'}"
        experiment_id = self._experiment_identity["experiment_id"]
        window_key = str(observation_window_id or "DAILY")
        uniqueness_key = f"{experiment_id}:{event_identity}:{event_start or 'TIME_UNKNOWN'}:{leg.market}:{getattr(leg, 'side', '')}:{leg.selection}:{getattr(leg, 'line', None)}:{date_key}:{window_key}"
        with self._file_lock():
            existing_record = self._find_existing_snapshot_by_key(uniqueness_key)
        if existing_record:
            # Idempotent return: do not write duplicate prediction
            return existing_record

        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"

        # Freshness indicators
        freshness = {
            "odds_status": getattr(leg, "odds_status", "UNKNOWN"),
            "odds_age_minutes": getattr(leg, "odds_age_minutes", 0.0),
            "model_provenances": evidence.get("model_provenances", []),
        }

        model_candidate_predictions = []
        for item in evidence.get("model_candidate_provenances", []):
            if not isinstance(item, dict):
                continue
            candidate_probability = finite_probability(item.get("raw_probability"))
            if candidate_probability is None:
                continue
            model_candidate_predictions.append({
                "model_id": item.get("model_id"),
                "model_version": item.get("model_version"),
                "league": str(leg.league),
                "market": str(leg.market),
                "source_scope": item.get("source_scope", "unknown"),
                "artifact_hash": item.get("artifact_hash"),
                "protocol_id": item.get("protocol_id"),
                "protocol_hash": item.get("protocol_hash"),
                "raw_probability": candidate_probability,
                "data_as_of": item.get("data_as_of"),
                "freshness_status": item.get("freshness_status"),
                "acceptance_status_at_prediction": item.get("acceptance_status", "NOT_EVALUATED"),
            })
        strategy_metadata = {**self._strategy_metadata, "experiment_identity": self._experiment_identity}
        record = {
            "snapshot_id": snapshot_id,
            "uniqueness_key": uniqueness_key,
            "observation_window_id": str(observation_window_id) if observation_window_id is not None else None,
            "snapshot_timestamp": now_iso,
            "timestamp": now_iso,  # backward compatibility
            "event_id": str(leg.event_id),
            "canonical_event_id": getattr(leg, "canonical_event_id", None),
            "source_game_id": getattr(leg, "source_game_id", None) or evidence.get("source_game_id") or evidence.get("game_pk"),
            "event_start": event_start,
            "sport": leg.sport,
            "league": leg.league,
            "away_team": getattr(leg, "away_team", ""),
            "home_team": getattr(leg, "home_team", ""),
            "market": leg.market,
            "selection": leg.selection,
            "side": getattr(leg, "side", ""),
            "line": getattr(leg, "line", None),
            "taiwan_odds": odds_value,
            "odds_timestamp": odds_scraped_at,
            "reference_odds": getattr(leg, "reference_odds", None),
            "market_implied_prob": round(market_implied, 4) if market_implied is not None else None,
            # Crowd
            "crowd_ratio": round(float(crowd_ratio), 4) if crowd_ratio is not None else None,
            "crowd_votes": int(crowd_votes) if crowd_votes is not None else None,
            "crowd_age_minutes": float(crowd_age) if crowd_age is not None else None,
            # Experts
            "verified_experts": experts,
            "expert_consensus": expert_consensus,
            "publication_time_precision": expert_precision,
            # Models
            "model_predictions": model_predictions,
            "model_probability": round(float(model_prob), 4) if model_prob is not None else None,
            "model_as_of": model_as_of,
            "model_probability_raw": finite_probability(evidence.get("model_probability_raw")) if has_model_estimate else None,
            "model_probability_calibrated": finite_probability(evidence.get("model_probability_calibrated")) if has_model_estimate else None,
            "model_candidate_probability_raw": finite_probability(evidence.get("model_candidate_probability_raw")),
            "model_candidate_probability_fused": finite_probability(evidence.get("model_candidate_probability_fused")),
            "model_candidate_provenances": copy.deepcopy(evidence.get("model_candidate_provenances", [])),
            "model_acceptance_statuses": copy.deepcopy(evidence.get("model_acceptance_statuses", [])),
            "model_candidate_predictions": model_candidate_predictions,
            "model_provenances": model_provenances,
            "model_fusion_groups": fusion_groups,
            "excluded_model_ids": excluded_model_ids,
            "probability_status": probability_status,
            "probability_source": "MODEL_FUSED_CONSENSUS" if has_model_estimate else "MARKET_BASELINE_ONLY",
            "model_market_delta": delta_pp,
            "model_market_delta_pp": delta_pp,
            # Probability & Edge Engine
            "expected_value": getattr(leg, "expected_value", None),
            "consensus_probability": finite_probability(getattr(leg, "consensus_probability", None)),
            "recommendation_probability": finite_probability(getattr(leg, "consensus_probability", None)),
            "calibrated_probability": finite_probability(getattr(leg, "calibrated_probability", None)),
            "market_fair_probability": evidence.get("market_fair_probability"),
            "market_fair_method": evidence.get("market_fair_method"),
            "market_evidence": {
                key: evidence.get(key) for key in (
                    "market_complete", "market_outcome_odds", "market_fair_probability",
                    "market_fair_method", "opposing_odds", "market_source", "market_observed_at",
                ) if key in evidence
            },
            "signal_evidence": copy.deepcopy(evidence),
            "lower_bound_90": getattr(leg, "lower_bound_90", None),
            # Evidence & agreement
            "evidence_quality": leg.evidence_quality,
            "agreement_badge": evidence.get("agreement_badge", ""),
            "quality_score": evidence.get("quality_score", 0.0),
            "independent_support_count": evidence.get("independent_support_count", 0),
            "supporting_groups": evidence.get("supporting_groups", []),
            "freshness": freshness,
            # Settlement Rule
            "settlement_rule_id": rule_id,
            "prediction_hash_schema": 4,
            # Governance & Eligibility
            "forward_validation_eligible": is_eligible,
            "exclusion_reason": exclusion_reason,
            "strategy_version": STRATEGY_VERSION,
            "strategy_metadata": copy.deepcopy(strategy_metadata),
            "experiment_identity": copy.deepcopy(self._experiment_identity),
            "strategy_config_hashes": self._strategy_metadata.get("config_hashes", {}),
            "expert_observed_at": evidence.get("expert_observed_at"),
            "signals": copy.deepcopy([s.to_dict() if hasattr(s, "to_dict") else s for s in getattr(leg, "signals", [])]),
            # Settlement Container (Initial State)
            "is_settled": False,
            "actual_outcome": None,
            "settlement_status": "PENDING",
            "settlement_reason": None,
            "final_score": None,
            "settled_at": None,
            "result_source": None,
            "brier_score": None,
            "log_loss": None,
            "closing_odds": None,
            "reference_closing_odds": None,
            "odds_clv_ratio": None,
            "clv_probability_pp": None,
            "clv_status": "NOT_AVAILABLE",
        }

        # Compute and attach cryptographic prediction payload hash
        record["prediction_payload_hash"] = compute_prediction_payload_hash(record)

        try:
            with self._file_lock():
                if self._find_existing_snapshot_by_key(uniqueness_key):
                    return self._find_existing_snapshot_by_key(uniqueness_key)
                append_jsonl(self.log_path, record)
        except Exception as exc:
            raise OSError(f"Failed to persist prediction snapshot {snapshot_id}: {exc}") from exc

        return record

    def log_batch(self, legs: List[TaiwanLeg], observation_window_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Record snapshots for multiple legs."""
        return [self.log_snapshot(leg, observation_window_id=observation_window_id) for leg in legs]

    def _find_existing_snapshot_by_key(self, uniqueness_key: str) -> Optional[Dict[str, Any]]:
        """Search existing snapshot log for duplicate key."""
        for data in read_jsonl(self.log_path):
            if data.get("uniqueness_key") == uniqueness_key:
                return data
        return None

    def get_all_snapshots(self) -> List[Dict[str, Any]]:
        """Read a locked complete ledger; malformed rows fail with line numbers."""
        return read_jsonl(self.log_path)

    def settle_prediction(
        self,
        snapshot_id: str,
        actual_outcome: Optional[bool],
        settlement_status: Optional[str] = None,
        settlement_reason: Optional[str] = None,
        final_score: Optional[str] = None,
        result_source: Optional[str] = "STATS_API",
        closing_odds: Optional[float] = None,
        reference_closing_odds: Optional[float] = None,
        closing_odds_source: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._file_lock():
            return self._settle_prediction_unlocked(
                snapshot_id, actual_outcome, settlement_status, settlement_reason,
                final_score, result_source, closing_odds, reference_closing_odds,
                closing_odds_source,
            )

    def _settle_prediction_unlocked(
        self,
        snapshot_id: str,
        actual_outcome: Optional[bool],
        settlement_status: Optional[str] = None,
        settlement_reason: Optional[str] = None,
        final_score: Optional[str] = None,
        result_source: Optional[str] = "STATS_API",
        closing_odds: Optional[float] = None,
        reference_closing_odds: Optional[float] = None,
        closing_odds_source: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Settle a snapshot with strict payload hash verification."""
        if not self.log_path.exists():
            return None

        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        updated_lines = []
        settled_record = None
        settled_time = datetime.now(timezone.utc).isoformat()

        for line in lines:
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("snapshot_id") == snapshot_id:
                # 1. Audit Check: Verify original prediction payload hash!
                expected_hash = data.get("prediction_payload_hash")
                if expected_hash:
                    current_hash = compute_prediction_payload_hash(data)
                    if current_hash != expected_hash:
                        raise AuditFailureError(
                            f"AUDIT_FAILURE: Original prediction payload has been altered for snapshot {snapshot_id}!"
                        )

                # Preserve the complete settlement state. Never infer a win from False.
                status = str(settlement_status or ("WON" if actual_outcome is True else "LOST" if actual_outcome is False else "UNRESOLVED")).upper()
                if status not in {"WON", "LOST", "PUSH", "VOID", "PENDING", "UNRESOLVED"}:
                    status = "UNRESOLVED"
                if (status == "WON" and actual_outcome is False) or (status == "LOST" and actual_outcome is True):
                    status = "UNRESOLVED"

                # 2. Probability & Metric Calculation (only binary resolved results).
                p = data.get("market_implied_prob", 0.5)
                valid_probability = data.get("probability_status") in {
                    "UNVALIDATED_MODEL_ESTIMATE", "MODEL_ESTIMATE", "CALIBRATED_MODEL_ESTIMATE"
                }
                pred_prob = data.get("model_probability") if valid_probability else None
                brier = logloss = None
                if status in {"WON", "LOST"} and pred_prob is not None and math.isfinite(float(pred_prob)) and 0.0 <= float(pred_prob) <= 1.0:
                    pred_prob = float(pred_prob)
                    outcome_numeric = 1.0 if status == "WON" else 0.0
                    brier = round((pred_prob - outcome_numeric) ** 2, 4)
                    p_clamped = max(0.001, min(0.999, pred_prob))
                    logloss = round(-(outcome_numeric * math.log(p_clamped) + (1.0 - outcome_numeric) * math.log(1.0 - p_clamped)), 4)

                # 3. Dual Closing Line Value (CLV) Calculation
                taiwan_odds = float(data.get("taiwan_odds", 1.0))
                odds_clv_ratio = None
                clv_prob_pp = None
                clv_status = "NOT_AVAILABLE"

                if closing_odds is not None and closing_odds > 1.0:
                    odds_clv_ratio = round((taiwan_odds / closing_odds) - 1.0, 4)
                    pred_imp = 1.0 / taiwan_odds
                    close_imp = 1.0 / closing_odds
                    clv_prob_pp = round((close_imp - pred_imp) * 100.0, 2)
                    clv_status = "BEAT_CLOSING" if taiwan_odds > closing_odds else "EQUAL_CLOSING" if taiwan_odds == closing_odds else "TRAIL_CLOSING"

                # 4. Append settlement fields without mutating prediction attributes
                data["actual_outcome"] = (status == "WON") if status in {"WON", "LOST"} else None
                data["is_settled"] = status in {"WON", "LOST", "PUSH", "VOID"}
                data["settlement_status"] = status
                data["settlement_reason"] = settlement_reason
                data["settled_at"] = settled_time
                data["final_score"] = final_score
                data["result_source"] = result_source
                data["brier_score"] = brier
                data["log_loss"] = logloss
                data["closing_odds"] = closing_odds
                data["reference_closing_odds"] = reference_closing_odds
                data["closing_odds_source"] = (
                    closing_odds_source if closing_odds is not None else None
                )
                data["odds_clv_ratio"] = odds_clv_ratio
                data["clv_probability_pp"] = clv_prob_pp
                data["clv_status"] = clv_status
                data["clv_beat"] = bool(odds_clv_ratio > 0) if odds_clv_ratio is not None else None

                settled_record = data

            updated_lines.append(json.dumps(data, ensure_ascii=False))

        if settled_record:
            atomic_write_bytes(self.log_path, ("\n".join(updated_lines) + "\n").encode("utf-8"))

        return settled_record

    def compute_calibration_metrics(self) -> Dict[str, Any]:
        """Compute aggregate Brier score and log loss across settled forward-eligible snapshots."""
        records = self.get_all_snapshots()
        brier_scores = []
        log_losses = []
        total = len(records)
        eligible_count = 0

        for data in records:
            if data.get("forward_validation_eligible") is True and data.get("strategy_version") == STRATEGY_VERSION:
                eligible_count += 1
            try:
                valid_model_probability = (
                    data.get("model_probability") is not None
                    and math.isfinite(float(data.get("model_probability")))
                )
            except (TypeError, ValueError, OverflowError):
                valid_model_probability = False
            if (data.get("forward_validation_eligible") is True and data.get("strategy_version") == STRATEGY_VERSION
                    and data.get("is_settled")
                    and data.get("probability_status") in {"UNVALIDATED_MODEL_ESTIMATE", "MODEL_ESTIMATE", "CALIBRATED_MODEL_ESTIMATE"}
                    and data.get("settlement_status") in {"WON", "LOST"}
                    and valid_model_probability
                    and data.get("brier_score") is not None and data.get("log_loss") is not None):
                brier_scores.append(data["brier_score"])
                log_losses.append(data.get("log_loss", 0.0))

        settled = len(brier_scores)
        return {
            "total_snapshots": total,
            "forward_eligible_count": eligible_count,
            "settled_count": settled,
            "mean_brier_score": round(sum(brier_scores) / settled, 4) if settled > 0 else None,
            "mean_log_loss": round(sum(log_losses) / settled, 4) if settled > 0 else None,
        }
