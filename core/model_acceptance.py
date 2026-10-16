"""Evidence-derived, point-in-time model qualification by exact scope.

Acceptance is calculated from immutable settled prediction snapshots. There is no
operator-controlled accepted flag: model, league, market, data source, executable
artifact, and probability protocol must all match the evidence cohort.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from probability.calibration import apply_binary_temperature, fit_binary_temperature
from core.experiment_identity import validate_experiment_identity
from core.snapshot_logger import compute_prediction_payload_hash
from core.research_paths import research_paths

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "model_acceptance.yaml"
SNAPSHOT_PATH = research_paths()["snapshots"]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _normalized_market_probability(snapshot: Mapping[str, Any]) -> float | None:
    """Return only a comparable, explicitly normalized market probability."""
    method = snapshot.get("market_fair_method")
    evidence = snapshot.get("market_evidence") or {}
    if not isinstance(evidence, Mapping):
        evidence = {}
    saved = _finite(snapshot.get("market_fair_probability"))
    odds = _finite(snapshot.get("taiwan_odds"))
    if saved is None or not 0 < saved < 1 or odds is None or odds <= 1:
        return None
    normalized = None
    if method == "COMPLETE_MARKET_PROPORTIONAL":
        outcomes = evidence.get("market_outcome_odds")
        side = snapshot.get("side")
        if snapshot.get("sport") == "soccer" and snapshot.get("market") in {"不讓分", "和局", "獨贏"}:
            expected_sides = {"主", "客", "和"}
        elif snapshot.get("market") == "大小":
            expected_sides = {"大", "小"}
        else:
            expected_sides = {"主", "客"}
        if not isinstance(outcomes, Mapping) or set(outcomes) != expected_sides or side not in outcomes:
            return None
        values = [_finite(value) for value in outcomes.values()]
        selected_odds = _finite(outcomes.get(side))
        if (selected_odds is None or not math.isclose(selected_odds, odds, rel_tol=0, abs_tol=1e-8)
                or any(value is None or value <= 1 for value in values)):
            return None
        normalized = (1.0 / selected_odds) / sum(1.0 / value for value in values)
    elif method == "TWO_WAY_PROPORTIONAL":
        opposing = _finite(evidence.get("opposing_odds"))
        if opposing is None or opposing <= 1:
            return None
        normalized = (1.0 / odds) / ((1.0 / odds) + (1.0 / opposing))
    if normalized is None or not 0 < normalized < 1:
        return None
    return normalized if math.isclose(saved, normalized, rel_tol=0, abs_tol=1e-6) else None


def protocol_hash(protocol: Mapping[str, Any]) -> str:
    body = json.dumps(dict(protocol), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def acceptance_evidence_hash(record: Mapping[str, Any]) -> str:
    fields = ("scope", "calibration_temperature", "calibration_n", "calibration_event_count",
              "evaluation_n", "evaluation_event_count", "evaluation_cluster_count",
              "calibration_max_prediction_timestamp", "calibration_outcomes_known_by",
              "evaluation_min_prediction_timestamp", "criteria", "metrics")
    body = {key: record.get(key) for key in fields}
    return protocol_hash(body)


def acceptance_matches_signal(signal: Any, leg: Any) -> bool:
    """Fail closed unless a computed acceptance record exactly matches signal scope."""
    metadata = getattr(signal, "metadata", None) or {}
    acceptance = metadata.get("model_acceptance") or {}
    scope = acceptance.get("scope") or {}
    temperature = _finite(acceptance.get("calibration_temperature"))
    raw_probability = _finite(metadata.get("model_candidate_probability"))
    calibrated_probability = _finite(metadata.get("model_calibrated_probability"))
    try:
        expected_calibrated = apply_binary_temperature(raw_probability, temperature)
    except (TypeError, ValueError):
        expected_calibrated = None
    criteria = acceptance.get("criteria") or {}
    provenance = metadata.get("calibration_provenance") or {}
    try:
        evidence_hash = acceptance_evidence_hash(acceptance)
    except (TypeError, ValueError):
        evidence_hash = None
    return bool(
        acceptance.get("accepted") is True
        and acceptance.get("status") == "ACCEPTED"
        and acceptance.get("evidence_derived") is True
        and acceptance.get("evidence_hash") == evidence_hash
        and isinstance(criteria, Mapping) and criteria
        and all(value is True for value in criteria.values())
        and temperature is not None and temperature > 0
        and _finite(acceptance.get("calibration_n")) is not None
        and _finite(acceptance.get("evaluation_n")) is not None
        and calibrated_probability is not None and expected_calibrated is not None
        and math.isclose(calibrated_probability, expected_calibrated, rel_tol=0, abs_tol=1e-12)
        and math.isclose(_finite(getattr(signal, "probability", None)) or -1,
                         expected_calibrated, rel_tol=0, abs_tol=1e-12)
        and provenance.get("temperature") == temperature
        and provenance.get("training_sample_size") == acceptance.get("calibration_n")
        and provenance.get("fit_cutoff") == acceptance.get("calibration_max_prediction_timestamp")
        and provenance.get("outcomes_known_by") == acceptance.get("calibration_outcomes_known_by")
        and provenance.get("protocol_id") == metadata.get("model_protocol_id")
        and scope.get("model_id") == metadata.get("model_id")
        and scope.get("model_version") == metadata.get("model_version")
        and scope.get("league") == getattr(leg, "league", None)
        and scope.get("market") == getattr(leg, "market", None)
        and scope.get("source_scope") == metadata.get("prediction_source_scope") == "taiwan_forward"
        and scope.get("artifact_hash") == metadata.get("model_artifact_hash")
        and scope.get("protocol_id") == metadata.get("model_protocol_id")
        and scope.get("protocol_hash") == metadata.get("model_protocol_hash")
        and isinstance(scope.get("artifact_hash"), str) and len(scope["artifact_hash"]) == 64
        and isinstance(scope.get("protocol_hash"), str) and len(scope["protocol_hash"]) == 64
    )


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    import yaml
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def read_snapshot_rows(path: Path = SNAPSHOT_PATH) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except (ValueError, TypeError):
            continue
    return rows


def _cluster_bootstrap_interval(rows: list[dict[str, Any]], key: str, *, rounds: int = 1200,
                                seed: int = 193) -> list[float] | None:
    """Bootstrap full event-date clusters while preserving the row-weighted mean."""
    clusters: dict[str, list[float]] = {}
    for row in rows:
        cluster = str(row.get("event_cluster") or row["prediction_timestamp"].date().isoformat())
        clusters.setdefault(cluster, []).append(float(row[key]))
    cluster_rows = list(clusters.values())
    if not cluster_rows:
        return None
    rng = random.Random(seed)
    samples = []
    n = len(cluster_rows)
    for _ in range(rounds):
        total = 0.0
        count = 0
        for _ in range(n):
            values = cluster_rows[rng.randrange(n)]
            total += sum(values)
            count += len(values)
        samples.append(total / count)
    samples.sort()
    return [samples[int(0.025 * (rounds - 1))], samples[int(0.975 * (rounds - 1))]]


def evaluate_scope_evidence(
    rows: Iterable[Mapping[str, Any]],
    *,
    model_id: str,
    model_version: str,
    league: str,
    market: str,
    source_scope: str,
    artifact_hash: str,
    protocol_id: str,
    protocol_hash_value: str,
    policy: Mapping[str, Any] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Evaluate a chronological train/evaluation cohort for one exact scope."""
    policy = dict(policy or {})
    cutoff = _date(as_of) if as_of else datetime.now(timezone.utc)
    if cutoff is None:
        return {"accepted": False, "status": "INVALID_AS_OF", "reason": "as_of_must_be_timezone_aware"}
    matched = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if (row.get("model_id"), row.get("model_version"), row.get("league"), row.get("market"),
                row.get("source_scope"), row.get("artifact_hash"), row.get("protocol_id"), row.get("protocol_hash")) != (
                model_id, model_version, league, market, source_scope, artifact_hash, protocol_id, protocol_hash_value):
            continue
        p = _finite(row.get("raw_probability"))
        y = row.get("outcome")
        timestamp = _date(row.get("prediction_timestamp"))
        settled_at = _date(row.get("settled_at"))
        event_start = _date(row.get("event_start"))
        market_p = _finite(row.get("market_probability"))
        odds = _finite(row.get("decimal_odds"))
        settlement_status = row.get("settlement_status")
        result_source = row.get("result_source")
        if (p is None or not 0 < p < 1 or type(y) not in {int, bool} or y not in (0, 1)
                or timestamp is None or settled_at is None or settled_at < timestamp
                or (event_start is not None and (timestamp >= event_start or settled_at < event_start))
                or settlement_status not in {"WON", "LOST"}
                or (settlement_status == "WON") != bool(y)
                or not isinstance(result_source, str) or not result_source.strip()
                or result_source.strip().upper() in {"UNKNOWN", "MANUAL", "TEST", "FIXTURE"}):
            continue
        if settled_at > cutoff:
            continue
        if market_p is None or not 0 < market_p < 1 or odds is None or odds <= 1:
            continue
        matched.append({**row, "raw_probability": p, "outcome": int(y), "prediction_timestamp": timestamp,
                        "settled_at": settled_at, "market_probability": market_p, "decimal_odds": odds})
    matched.sort(key=lambda row: (row["prediction_timestamp"], str(row.get("event_id", ""))))
    # Keep one earliest forecast per exact event/market/selection; contradictory
    # settlements for the same key are removed from the evidence cohort.
    deduped: dict[tuple, list[dict[str, Any]]] = {}
    for row in matched:
        dedupe_key = (str(row.get("event_id", "")), str(row.get("league", "")),
                      str(row.get("market", "")), str(row.get("side", "")), str(row.get("line", "")))
        deduped.setdefault(dedupe_key, []).append(row)
    matched = []
    for group in deduped.values():
        if len({row["outcome"] for row in group}) == 1:
            matched.append(group[0])
    matched.sort(key=lambda row: (row["prediction_timestamp"], str(row.get("event_id", ""))))
    train_min = int(policy.get("min_calibration_samples", 100))
    eval_min = int(policy.get("min_evaluation_samples", 100))
    result = {"accepted": False, "status": "INSUFFICIENT_EVIDENCE", "reason": "insufficient_chronological_evidence",
              "scope": {"model_id": model_id, "model_version": model_version, "league": league,
                        "market": market, "source_scope": source_scope, "artifact_hash": artifact_hash,
                        "protocol_id": protocol_id, "protocol_hash": protocol_hash_value},
              "calibration_n": 0, "evaluation_n": 0}
    if source_scope != "taiwan_forward":
        result.update(status="HISTORICAL_ONLY", reason="non_taiwan_source_cannot_grant_runtime_acceptance",
                      matched_rows=len(matched))
        return result
    if len(matched) < train_min + eval_min:
        result["matched_rows"] = len(matched)
        return result
    # Fit on a chronological prefix of whole events so a three-way market's
    # multiple selections cannot inflate its sample count or split train/eval.
    event_groups: dict[str, list[dict[str, Any]]] = {}
    for row in matched:
        event_groups.setdefault(str(row.get("event_id", "")), []).append(row)
    chronological_events = sorted(
        event_groups.items(),
        key=lambda item: min(row["prediction_timestamp"] for row in item[1]),
    )
    train: list[dict[str, Any]] = []
    training_event_ids: set[str] = set()
    for event_id, event_rows in chronological_events:
        if not event_id:
            continue
        train.extend(event_rows)
        training_event_ids.add(event_id)
        if (len(train) >= train_min
                and len(training_event_ids) >= int(policy.get("min_calibration_events", 100))):
            break
    if not train:
        return result
    train.sort(key=lambda row: (row["prediction_timestamp"], str(row.get("event_id", ""))))
    train_outcome_cutoff = max(row["settled_at"] for row in train)
    training_events = training_event_ids
    min_train_events = int(policy.get("min_calibration_events", 100))
    if len(training_events - {""}) < min_train_events:
        result.update(status="INSUFFICIENT_CALIBRATION_EVENTS", reason="too_few_unique_calibration_events",
                      calibration_n=len(train), calibration_event_count=len(training_events - {""}))
        return result
    evaluation = [row for event_id, event_rows in chronological_events if event_id not in training_events
                  for row in event_rows if row["prediction_timestamp"] > train_outcome_cutoff]
    evaluation.sort(key=lambda row: (row["prediction_timestamp"], str(row.get("event_id", ""))))
    if not evaluation or max(row["settled_at"] for row in train) >= min(
            row["prediction_timestamp"] for row in evaluation):
        result.update(status="INVALID_CHRONOLOGY", reason="training_and_evaluation_windows_overlap")
        return result
    temperature = fit_binary_temperature([r["raw_probability"] for r in train], [r["outcome"] for r in train])
    if temperature is None:
        result.update(status="CALIBRATION_UNAVAILABLE", reason="training_data_cannot_fit_calibrator")
        return result
    scored = []
    min_model_ev = float(policy.get("minimum_expected_value", 0.05))
    for row in evaluation:
        p = apply_binary_temperature(row["raw_probability"], temperature)
        market_p = row["market_probability"]
        y = row["outcome"]
        p = max(1e-6, min(1 - 1e-6, p))
        market_p = max(1e-6, min(1 - 1e-6, market_p))
        model_ev = p * row["decimal_odds"] - 1.0
        market_ev = market_p * row["decimal_odds"] - 1.0
        model_return = (row["decimal_odds"] - 1 if y else -1) if model_ev is not None and model_ev >= min_model_ev else 0.0
        market_return = (row["decimal_odds"] - 1 if y else -1) if market_ev is not None and market_ev >= min_model_ev else 0.0
        event_start = _date(row.get("event_start"))
        event_cluster = event_start.date().isoformat() if event_start else row["prediction_timestamp"].date().isoformat()
        scored.append({"prediction_timestamp": row["prediction_timestamp"], "event_id": row.get("event_id"),
                       "event_cluster": event_cluster,
                       "model_brier": (p-y)**2, "market_brier": (market_p-y)**2,
                       "model_logloss": -(y*math.log(p)+(1-y)*math.log(1-p)),
                       "market_logloss": -(y*math.log(market_p)+(1-y)*math.log(1-market_p)),
                       "model_return": model_return, "market_return": market_return,
                       "roi_delta": model_return-market_return})
    evaluation_clusters = len({row["event_cluster"] for row in scored})
    evaluation_events = len({str(row.get("event_id", "")) for row in scored} - {""})
    if (len(scored) < eval_min
            or evaluation_events < int(policy.get("min_evaluation_events", 30))
            or evaluation_clusters < int(policy.get("min_evaluation_clusters", 30))):
        result.update(status="INSUFFICIENT_EVALUATION", reason="too_few_comparable_market_rows",
                      calibration_n=len(train), evaluation_n=len(scored),
                      evaluation_event_count=evaluation_events, evaluation_cluster_count=evaluation_clusters)
        return result
    brier_deltas = [x["model_brier"] - x["market_brier"] for x in scored]
    logloss_deltas = [x["model_logloss"] - x["market_logloss"] for x in scored]
    rounds = int(policy.get("bootstrap_rounds", 1200))
    seed = int(policy.get("bootstrap_seed", 193))
    brier_rows = [{"prediction_timestamp": x["prediction_timestamp"], "value": x["model_brier"]-x["market_brier"]} for x in scored]
    logloss_rows = [{"prediction_timestamp": x["prediction_timestamp"], "value": x["model_logloss"]-x["market_logloss"]} for x in scored]
    roi_rows = [{"prediction_timestamp": x["prediction_timestamp"], "value": x["roi_delta"]} for x in scored]
    brier_ci = _cluster_bootstrap_interval(brier_rows, "value", rounds=rounds, seed=seed)
    logloss_ci = _cluster_bootstrap_interval(logloss_rows, "value", rounds=rounds, seed=seed)
    roi_ci = _cluster_bootstrap_interval(roi_rows, "value", rounds=rounds, seed=seed)
    model_returns = [x["model_return"] for x in scored if x["model_return"] != 0.0]
    min_decisions = int(policy.get("min_roi_decisions", 30))
    improves_brier = bool(brier_ci and brier_ci[1] < 0)
    improves_logloss = bool(logloss_ci and logloss_ci[1] < 0)
    roi_positive = bool(len(model_returns) >= min_decisions and roi_ci
                        and roi_ci[0] > float(policy.get("roi_delta_lower_bound_min", 0.0)))
    accepted = improves_brier and improves_logloss and roi_positive
    result.update({"accepted": accepted, "status": "ACCEPTED" if accepted else "REJECTED",
                   "reason": "all_predeclared_metrics_passed" if accepted else "benchmark_gate_failed",
                   "calibration_n": len(train), "evaluation_n": len(scored),
                   "calibration_event_count": len(training_events - {""}),
                   "evaluation_event_count": evaluation_events,
                   "evaluation_cluster_count": evaluation_clusters,
                   "calibration_temperature": temperature,
                   "calibration_max_prediction_timestamp": train[-1]["prediction_timestamp"].isoformat(),
                   "calibration_outcomes_known_by": train_outcome_cutoff.isoformat(),
                   "evaluation_min_prediction_timestamp": evaluation[0]["prediction_timestamp"].isoformat(),
                   "metrics": {"paired_brier_delta_mean": sum(brier_deltas)/len(brier_deltas),
                               "paired_brier_delta_95_ci": brier_ci,
                               "paired_logloss_delta_mean": sum(logloss_deltas)/len(logloss_deltas),
                               "paired_logloss_delta_95_ci": logloss_ci,
                               "model_roi_decision_count": len(model_returns),
                               "model_roi_per_bet_mean": sum(model_returns)/len(model_returns) if model_returns else None,
                               "paired_roi_delta_mean_per_prediction": sum(x["roi_delta"] for x in scored)/len(scored),
                               "paired_roi_delta_cluster_95_ci": roi_ci},
                   "criteria": {"brier_upper_below_zero": improves_brier,
                                "logloss_upper_below_zero": improves_logloss,
                                "roi_lower_above_policy": roi_positive}})
    if accepted:
        result["evidence_derived"] = True
        result["evidence_hash"] = acceptance_evidence_hash(result)
    return result


class ModelAcceptanceGate:
    """Runtime lookup against the immutable settled snapshot ledger."""
    def __init__(self, snapshot_path: Path | None = None, policy_path: Path = POLICY_PATH):
        self.snapshot_path = Path(snapshot_path or SNAPSHOT_PATH)
        self.policy_path = Path(policy_path)
        self.policy = load_policy(self.policy_path)
        self._rows_signature: tuple[int, int] | None = None
        self._rows_cache: list[dict[str, Any]] = []

    def _rows(self) -> list[dict[str, Any]]:
        if not self.snapshot_path.exists():
            self._rows_signature = None
            self._rows_cache = []
            return []
        stat = self.snapshot_path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature != self._rows_signature:
            self._rows_cache = read_snapshot_rows(self.snapshot_path)
            self._rows_signature = signature
        return self._rows_cache

    def status(self, *, model_id: str, model_version: str, league: str, market: str,
               source_scope: str, artifact_hash: str, protocol_id: str, protocol_hash_value: str,
               as_of: str | None = None) -> dict[str, Any]:
        if as_of is not None and _date(as_of) is None:
            return {"accepted": False, "status": "INVALID_AS_OF", "reason": "as_of_must_be_timezone_aware"}
        rows = self._rows()
        evidence = []
        excluded_incomplete_market = 0
        for snapshot in rows:
            snapshot_time = _date(snapshot.get("snapshot_timestamp"))
            settled_at = _date(snapshot.get("settled_at"))
            event_start = _date(snapshot.get("event_start"))
            requested_as_of = _date(as_of) if as_of else datetime.now(timezone.utc)
            if (snapshot_time is None or settled_at is None or event_start is None or requested_as_of is None
                    or snapshot_time >= event_start or settled_at < event_start
                    or settled_at > requested_as_of or snapshot_time >= requested_as_of):
                continue
            if (snapshot.get("is_settled") is not True or snapshot.get("settlement_status") not in {"WON", "LOST"}
                    or snapshot.get("forward_validation_eligible") is not True
                    or snapshot.get("prediction_hash_schema", 1) < 4):
                continue
            identity = snapshot.get("experiment_identity")
            if (not validate_experiment_identity(identity)
                    or identity.get("strategy_version") != snapshot.get("strategy_version")
                    or not isinstance(snapshot.get("strategy_metadata"), dict)
                    or snapshot["strategy_metadata"].get("experiment_identity") != identity
                    or snapshot.get("strategy_config_hashes") != identity.get("config_hashes")
                    or snapshot.get("prediction_payload_hash") != compute_prediction_payload_hash(snapshot)):
                continue
            if (snapshot.get("actual_outcome") is not (snapshot.get("settlement_status") == "WON")
                    or not isinstance(snapshot.get("result_source"), str)
                    or not snapshot.get("result_source").strip()
                    or snapshot.get("result_source").strip().upper() in {"UNKNOWN", "MANUAL", "TEST", "FIXTURE"}):
                continue
            outcome = 1 if snapshot.get("settlement_status") == "WON" else 0
            market_probability = _normalized_market_probability(snapshot)
            if market_probability is None:
                excluded_incomplete_market += 1
                continue
            for prediction in snapshot.get("model_candidate_predictions", []):
                if isinstance(prediction, Mapping):
                    pred = dict(prediction)
                    pred.update({"prediction_timestamp": snapshot.get("snapshot_timestamp"),
                                 "event_id": snapshot.get("canonical_event_id") or snapshot.get("event_id"),
                                 "side": snapshot.get("side") or snapshot.get("pick"),
                                 "line": snapshot.get("line"),
                                 "event_start": snapshot.get("event_start"),
                                 "outcome": outcome, "market_probability": market_probability,
                                 "decimal_odds": snapshot.get("taiwan_odds"),
                                 "settled_at": snapshot.get("settled_at"),
                                 "settlement_status": snapshot.get("settlement_status"),
                                 "result_source": snapshot.get("result_source")})
                    data_as_of = _date(pred.get("data_as_of"))
                    snapshot_time = _date(pred.get("prediction_timestamp"))
                    event_start = _date(snapshot.get("event_start"))
                    if (data_as_of is None or snapshot_time is None or event_start is None
                            or data_as_of > snapshot_time or data_as_of >= event_start
                            or pred.get("freshness_status") not in {"LIVE", "FRESH", "AGING"}):
                        continue
                    evidence.append(pred)
        result = evaluate_scope_evidence(evidence, model_id=model_id, model_version=model_version,
                                         league=league, market=market, source_scope=source_scope,
                                         artifact_hash=artifact_hash, protocol_id=protocol_id,
                                         protocol_hash_value=protocol_hash_value,
                                         policy=self.policy.get("gate", self.policy), as_of=as_of)
        result["evidence_snapshot_count"] = len(rows)
        result["incomplete_or_invalid_market_benchmark_excluded"] = excluded_incomplete_market
        return result
