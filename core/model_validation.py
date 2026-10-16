"""Reproducible, point-in-time validation for Football-Data.co.uk soccer records.

This is external historical research. Its bookmaker prices and ROI are not
Taiwan Sports Lottery prices or forward product validation.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import random
import os
import unicodedata
from typing import Any, Callable, Iterable, Optional

import penaltyblog as pb

from core.edge_engine import DEFAULT_BETA_MODEL
from core.identity import GLOBAL_TEAM_REGISTRY
from core.strategy_version import STRATEGY_VERSION, get_strategy_metadata
from core.experiment_identity import build_experiment_identity

VALIDATION_SCHEMA = "historical-model-validation-v1"
SUPPORTED_LEAGUES = {"eng.1": "E0", "esp.1": "SP1"}
SUPPORTED_SEASONS = ("2324", "2425", "2526")
SEASON_NAMES = {"2324": "2023/24", "2425": "2024/25", "2526": "2025/26"}
XI_CANDIDATES = (0.0012, 0.0018, 0.0024)
MIN_TRAIN_MATCHES = 60
MIN_TEAM_APPEARANCES = 4
ROI_MIN_EV = 0.05
UNIT_STAKE = 1.0
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_SEED = 20261013
PREREGISTRATION_SCHEMA = "model-evaluation-preregistration-v2"
EVALUATION_MANIFEST_SCHEMA = "prospective-model-evaluation-manifest-v1"
PRODUCTION_VALIDATION_SCOPE = {
    "validated_external_leagues": sorted(SUPPORTED_LEAGUES),
    "unsupported_production_sports": ["MLB", "NPB", "CPBL", "KBO", "NBA/WNBA", "NFL", "other soccer leagues"],
    "reason": "Frozen audited Football-Data.co.uk point-in-time match and B365 H/D/A sources currently cover only English Premier League and Spanish La Liga; Taiwan production market snapshots are not interchangeable with these sources.",
}


@dataclass(frozen=True)
class MatchRecord:
    league: str
    season: str
    match_date: date
    home_team: str
    away_team: str
    home_key: str
    away_key: str
    home_goals: int
    away_goals: int
    odds_h: Optional[float]
    odds_d: Optional[float]
    odds_a: Optional[float]
    source_filename: str
    source_sha256: str
    source_row_number: int
    team_resolution: str

    @property
    def row_key(self) -> tuple[str, str, str, str]:
        return (self.league, self.match_date.isoformat(), self.home_key, self.away_key)

    @property
    def outcome(self) -> int:
        if self.home_goals > self.away_goals:
            return 0
        if self.home_goals == self.away_goals:
            return 1
        return 2

    @property
    def max_train_date(self) -> None:
        return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def preregister_model_evaluation(path: Path, *, evaluation_id: str, league: str,
                                 training_source_identity_sha256: str,
                                 model_artifact_sha256: str, protocol: dict[str, Any],
                                 evaluation_start: str, evaluation_end: str) -> dict[str, Any]:
    """Pin the known training source/model/protocol before a future eval window.

    The future evaluation dataset hash is intentionally absent: it is frozen
    and identified only after the evaluation window has ended.
    """
    if not isinstance(evaluation_id, str) or not evaluation_id.strip() or not isinstance(league, str) or not league.strip():
        raise ValueError("evaluation_id and league are required")
    if not isinstance(protocol, dict) or not protocol:
        raise ValueError("A non-empty, predeclared evaluation protocol is required")
    hashes = (training_source_identity_sha256, model_artifact_sha256)
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        raise ValueError("Data and model identities must be lowercase SHA-256 hashes")
    start = _parse_date(evaluation_start)
    end = _parse_date(evaluation_end)
    registered = datetime.now(timezone.utc)
    if start is None or end is None or start > end or start <= registered.date():
        raise ValueError("Register before a valid future evaluation window starts and ends")
    payload = {"schema": PREREGISTRATION_SCHEMA, "evaluation_id": evaluation_id,
               "league": league, "registered_at_utc": registered.isoformat(),
               "evaluation_start": start.isoformat(), "evaluation_end": end.isoformat(),
               "training_source_identity_sha256": training_source_identity_sha256,
               "model_artifact_sha256": model_artifact_sha256,
               "protocol": protocol}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    record = {**payload, "preregistration_sha256": _sha256(canonical.encode("utf-8"))}
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FileExistsError(f"Evaluation plan is immutable and already exists: {destination}") from exc
    return record


def verify_preregistration(record: Any) -> bool:
    """Verify content integrity of a preregistration record."""
    if not isinstance(record, dict) or record.get("schema") != PREREGISTRATION_SCHEMA:
        return False
    digest = record.get("preregistration_sha256")
    payload = {key: value for key, value in record.items() if key != "preregistration_sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return isinstance(digest, str) and digest == _sha256(canonical.encode("utf-8"))


def finalize_preregistered_evaluation(registration_path: Path, manifest_path: Path,
                                      output_path: Path) -> dict[str, Any]:
    """Score a frozen manifest after its full evaluation period has elapsed.

    This creates an auditable report eligible for independent review; it never
    marks a model accepted by the runtime gate.
    """
    registration = json.loads(Path(registration_path).read_text(encoding="utf-8"))
    if not verify_preregistration(registration):
        raise ValueError("Registration identity/hash is invalid")
    now = datetime.now(timezone.utc)
    window_end = date.fromisoformat(registration["evaluation_end"])
    if now.date() <= window_end:
        raise ValueError("Evaluation window has not ended; no prospective evaluation report is issued")
    manifest_bytes = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != EVALUATION_MANIFEST_SCHEMA:
        raise ValueError("Unsupported frozen evaluation manifest")
    supplied_hash = manifest.get("manifest_sha256")
    hash_payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    actual_manifest_hash = _sha256(json.dumps(hash_payload, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode("utf-8"))
    if supplied_hash != actual_manifest_hash:
        raise ValueError("Evaluation manifest content hash does not match")
    if (manifest.get("evaluation_id") != registration["evaluation_id"]
            or manifest.get("training_source_identity_sha256") != registration["training_source_identity_sha256"]
            or manifest.get("model_artifact_sha256") != registration["model_artifact_sha256"]):
        raise ValueError("Frozen evaluation data/model identity differs from preregistration")
    if manifest.get("frozen") is not True or manifest.get("holdout_frozen") is not True:
        raise ValueError("Evaluation and holdout must both be explicitly frozen")
    finalized_at = _aware_utc(manifest.get("finalized_at_utc"))
    if finalized_at is None or finalized_at.date() <= window_end or finalized_at > now:
        raise ValueError("Manifest freeze timestamp must be aware, after evaluation end, and not in the future")
    source_hashes = manifest.get("source_hashes")
    if not isinstance(source_hashes, list) or not source_hashes:
        raise ValueError("Frozen manifest must list hashed result/prediction sources")
    known_hashes = set()
    for source in source_hashes:
        if (not isinstance(source, dict) or not source.get("source_url")
                or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", "")))):
            raise ValueError("Each source record needs a URL and SHA-256")
        retrieved_at = _aware_utc(source.get("retrieved_at_utc"))
        if retrieved_at is None or retrieved_at > now:
            raise ValueError("Source records need an aware, non-future retrieval timestamp")
        known_hashes.add(source["sha256"])
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Frozen evaluation manifest has no scored prediction rows")
    start_date = date.fromisoformat(registration["evaluation_start"])
    scored, market_scored, seen_events = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Evaluation rows must be objects")
        event_id = str(row.get("canonical_event_id") or row.get("event_id") or "").strip()
        prediction_at = _aware_utc(row.get("prediction_timestamp"))
        source_as_of = _aware_utc(row.get("source_as_of"))
        event_start = _aware_utc(row.get("event_start"))
        settled_at = _aware_utc(row.get("settled_at"))
        if (not event_id or prediction_at is None or source_as_of is None
                or event_start is None or settled_at is None):
            raise ValueError("Rows need event identity and aware source/prediction/start/settlement timestamps")
        if (row.get("model_artifact_sha256") != registration["model_artifact_sha256"]
                or row.get("training_source_identity_sha256") != registration["training_source_identity_sha256"]):
            raise ValueError("Prediction row model/training identity differs from preregistration")
        if row.get("prediction_source_sha256") not in known_hashes:
            raise ValueError("Point-in-time model input source is not covered by the frozen manifest")
        if not start_date <= event_start.date() <= window_end:
            raise ValueError("Evaluation event falls outside preregistered date window")
        if not source_as_of <= prediction_at < event_start <= settled_at <= finalized_at:
            raise ValueError("Source/prediction/result timestamps violate point-in-time chronology")
        if row.get("result_source_sha256") not in known_hashes:
            raise ValueError("Settled outcome source is not covered by the frozen manifest")
        if event_id in seen_events:
            raise ValueError("Duplicate event rows are not allowed in this multiclass evaluation")
        seen_events.add(event_id)
        outcome_raw = row.get("outcome")
        outcome_map = {"HOME": 0, "DRAW": 1, "AWAY": 2}
        outcome = outcome_map.get(str(outcome_raw).upper(), outcome_raw)
        if isinstance(outcome, bool) or outcome not in (0, 1, 2):
            raise ValueError("Outcome must be HOME/DRAW/AWAY or integer 0/1/2")
        model_probs = _strict_probability_vector(row.get("model_probabilities"))
        if model_probs is None:
            raise ValueError("Model probabilities must be a finite normalized H/D/A vector")
        scored.append((model_probs, int(outcome)))
        market_probs = _strict_probability_vector(row.get("market_probabilities"))
        if row.get("market_probabilities") is not None and market_probs is None:
            raise ValueError("Provided market probability vectors must be finite and normalized")
        if market_probs is not None:
            market_scored.append((event_id, model_probs, market_probs, int(outcome)))
    model_metrics = multiclass_metrics([pair[0] for pair in scored], [pair[1] for pair in scored])
    common = [row for row in market_scored]
    same_cohort = {"n": len(common), "model": None, "market": None}
    if common:
        same_cohort["model"] = multiclass_metrics([row[1] for row in common], [row[3] for row in common])
        same_cohort["market"] = multiclass_metrics([row[2] for row in common], [row[3] for row in common])
    report = {"schema": "preregistered-model-evaluation-report-v1",
              "evaluation_id": registration["evaluation_id"], "league": registration["league"],
              "status": "COMPLETED_FROZEN_EVALUATION",
              "prospective_review_status": "ELIGIBLE_FOR_INDEPENDENT_REVIEW_NOT_AUTOMATICALLY_ACCEPTED",
              "registration_sha256": registration["preregistration_sha256"],
              "evaluation_manifest_sha256": _sha256(manifest_bytes),
              "training_source_identity_sha256": registration["training_source_identity_sha256"],
              "model_artifact_sha256": registration["model_artifact_sha256"],
              "evaluation_window": {"start": registration["evaluation_start"], "end": registration["evaluation_end"]},
              "generated_at_utc": now.isoformat(), "sample_size_unique_events": len(scored),
              "model_metrics": model_metrics, "market_comparison_same_cohort": same_cohort,
              "source_hashes": source_hashes, "protocol": registration["protocol"],
              "limitation": "A frozen report is not a runtime acceptance certificate and does not establish profitability."}
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise FileExistsError(f"Evaluation reports are immutable: {destination}") from exc
    return report


def _aware_utc(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else None


def _strict_probability_vector(value: Any) -> Optional[tuple[float, float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or item < 0 for item in value):
        return None
    vector = tuple(float(item) for item in value)
    return vector if abs(sum(vector) - 1.0) <= 1e-6 else None


def _parse_date(raw: Any) -> Optional[date]:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_score(raw: Any) -> Optional[int]:
    text = str(raw or "").strip()
    if not re.fullmatch(r"\d+", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_odds(raw: Any) -> tuple[Optional[float], str]:
    text = str(raw or "").strip()
    if not text:
        return None, "MISSING"
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None, "NON_NUMERIC"
    if not math.isfinite(value):
        return None, "NON_FINITE"
    if not 1.01 <= value <= 100.0:
        return None, "OUT_OF_RANGE"
    return value, "VALID"


def _team_name(value: Any) -> tuple[Optional[str], str, str]:
    raw = str(value or "").strip()
    if not raw:
        return None, "", "MISSING"
    # Exact registry match only. The registry's general resolver also permits
    # substring matches, which are too ambiguous for historical identity joins.
    team = GLOBAL_TEAM_REGISTRY._lookup.get(raw.casefold())
    if team and team.sport == "soccer":
        return team.canonical_id, team.display_name_en, "REGISTRY"
    normalized = unicodedata.normalize("NFKC", raw).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    normalized = " ".join(normalized.split())
    if not normalized:
        return None, raw, "UNRESOLVED"
    # Keep an explicit source-name key; this is not an inferred alias mapping.
    return f"SOURCE:{normalized}", raw, "SOURCE_NAME_UNMAPPED"


def _manifest(source_dir: Path) -> dict[str, Any]:
    manifests = sorted(source_dir.glob("manifest_*.json"), key=lambda p: p.name)
    if not manifests:
        raise FileNotFoundError(f"No immutable source manifest in {source_dir}")
    path = manifests[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "football-data-source-manifest-v1":
        raise ValueError(f"Unsupported source manifest: {path}")
    return {**data, "_manifest_path": str(path), "_manifest_sha256": _sha256(path.read_bytes())}


def _read_csv_bytes(path: Path) -> list[dict[str, str]]:
    content = path.read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="strict")
    reader = csv.DictReader(text.splitlines())
    required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "B365H", "B365D", "B365A"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{path.name} is not a compatible Football-Data CSV; missing columns: {sorted(missing)}")
    rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} contains no match records")
    return rows


def _row_signature(row: MatchRecord) -> tuple[Any, ...]:
    return (row.home_goals, row.away_goals, row.odds_h, row.odds_d, row.odds_a)


def load_validation_dataset(source_dir: Path, league: str) -> tuple[list[MatchRecord], dict[str, Any]]:
    """Load, canonicalize, profile and dedupe one league without last-row-wins."""
    if league not in SUPPORTED_LEAGUES:
        raise ValueError(f"Unsupported league {league!r}; choose one of {sorted(SUPPORTED_LEAGUES)}")
    source_dir = Path(source_dir)
    manifest = _manifest(source_dir)
    downloads = manifest.get("downloads", [])
    entries = [item for item in downloads if item.get("league") == league and item.get("season") in SUPPORTED_SEASONS]
    present_seasons = {str(item.get("season")) for item in entries}
    if present_seasons != set(SUPPORTED_SEASONS):
        raise ValueError(f"Frozen validation requires seasons {SUPPORTED_SEASONS}; found {sorted(present_seasons)}")
    rows_by_key: dict[tuple[str, str, str, str], list[MatchRecord]] = {}
    exclusions: dict[str, int] = {}
    profile: dict[str, Any] = {
        "input_rows": 0, "valid_rows_before_dedup": 0, "unique_games": 0,
        "duplicate_rows_removed": 0, "conflicting_duplicate_groups": 0,
        "unknown_team_name_rows": 0, "missing_date_rows": 0, "invalid_score_rows": 0,
        "complete_market_rows": 0, "incomplete_market_rows": 0,
        "invalid_market_price_cells": 0, "date_min": None, "date_max": None,
        "team_names": {}, "odds_ranges": {"H": [], "D": [], "A": []},
    }
    used_sources = []
    notes_entries = [item for item in downloads if item.get("league") == "notes"]
    if not notes_entries:
        raise ValueError("The source manifest must include official notes.txt")
    for entry in notes_entries:
        filename = entry.get("stored_filename")
        if entry.get("http_status") != 200 or not filename or Path(filename).name != filename:
            raise ValueError("The official notes.txt entry is invalid")
        path = source_dir / filename
        digest = _sha256(path.read_bytes())
        if digest != entry.get("sha256"):
            raise ValueError("Official notes.txt hash mismatch")
        used_sources.append({key: entry.get(key) for key in (
            "league", "season", "source_url", "stored_filename", "sha256", "retrieved_at_utc", "http_status")})
    for entry in entries:
        if entry.get("http_status") != 200 or entry.get("error"):
            raise ValueError(f"Source manifest contains unsuccessful fetch: {entry}")
        filename = entry.get("stored_filename")
        if not filename or Path(filename).name != filename:
            raise ValueError("Manifest source filename is not a safe basename")
        source_path = source_dir / filename
        content = source_path.read_bytes()
        digest = _sha256(content)
        if digest != entry.get("sha256"):
            raise ValueError(f"Source hash mismatch for {filename}")
        used_sources.append({key: entry.get(key) for key in (
            "league", "season", "source_url", "stored_filename", "sha256", "retrieved_at_utc", "http_status")})
        for row_number, raw in enumerate(_read_csv_bytes(source_path), start=2):
            profile["input_rows"] += 1
            match_date = _parse_date(raw.get("Date"))
            if match_date is None:
                exclusions["UNKNOWN_OR_INVALID_DATE"] = exclusions.get("UNKNOWN_OR_INVALID_DATE", 0) + 1
                profile["missing_date_rows"] += 1
                continue
            home_key, home_name, home_resolution = _team_name(raw.get("HomeTeam"))
            away_key, away_name, away_resolution = _team_name(raw.get("AwayTeam"))
            if not home_key or not away_key:
                exclusions["MISSING_TEAM"] = exclusions.get("MISSING_TEAM", 0) + 1
                continue
            if "SOURCE_NAME_UNMAPPED" in {home_resolution, away_resolution}:
                profile["unknown_team_name_rows"] += 1
            profile["team_names"][home_key] = profile["team_names"].get(home_key, 0) + 1
            profile["team_names"][away_key] = profile["team_names"].get(away_key, 0) + 1
            hg, ag = _parse_score(raw.get("FTHG")), _parse_score(raw.get("FTAG"))
            if hg is None or ag is None:
                exclusions["INVALID_OR_MISSING_SCORE"] = exclusions.get("INVALID_OR_MISSING_SCORE", 0) + 1
                profile["invalid_score_rows"] += 1
                continue
            parsed_odds: dict[str, Optional[float]] = {}
            for side, col in (("H", "B365H"), ("D", "B365D"), ("A", "B365A")):
                value, status = _parse_odds(raw.get(col))
                parsed_odds[side] = value
                if status == "VALID":
                    profile["odds_ranges"][side].append(value)
                elif status != "MISSING":
                    profile["invalid_market_price_cells"] += 1
            complete_market = all(parsed_odds[s] is not None for s in ("H", "D", "A"))
            if complete_market:
                profile["complete_market_rows"] += 1
            else:
                profile["incomplete_market_rows"] += 1
            record = MatchRecord(
                league=league, season=str(entry["season"]), match_date=match_date,
                home_team=home_name, away_team=away_name, home_key=home_key, away_key=away_key,
                home_goals=hg, away_goals=ag, odds_h=parsed_odds["H"], odds_d=parsed_odds["D"],
                odds_a=parsed_odds["A"], source_filename=filename, source_sha256=digest,
                source_row_number=row_number,
                team_resolution="REGISTRY" if home_resolution == away_resolution == "REGISTRY" else "MIXED_OR_SOURCE_NAME",
            )
            rows_by_key.setdefault(record.row_key, []).append(record)

    accepted: list[MatchRecord] = []
    for _, group in sorted(rows_by_key.items()):
        signatures = {_row_signature(row) for row in group}
        if len(signatures) > 1:
            profile["conflicting_duplicate_groups"] += 1
            exclusions["CONFLICTING_DUPLICATE_ROW_KEY"] = exclusions.get("CONFLICTING_DUPLICATE_ROW_KEY", 0) + len(group)
            continue
        accepted.append(sorted(group, key=lambda item: (item.season, item.source_filename, item.source_row_number))[0])
        profile["duplicate_rows_removed"] += max(0, len(group) - 1)
    accepted.sort(key=lambda row: (row.match_date, row.home_key, row.away_key))
    profile["valid_rows_before_dedup"] = sum(len(group) for group in rows_by_key.values())
    profile["unique_games"] = len(accepted)
    profile["date_min"] = min((r.match_date for r in accepted), default=None)
    profile["date_max"] = max((r.match_date for r in accepted), default=None)
    profile["date_min"] = profile["date_min"].isoformat() if profile["date_min"] else None
    profile["date_max"] = profile["date_max"].isoformat() if profile["date_max"] else None
    profile["odds_ranges"] = {
        side: {"min": min(values), "max": max(values), "valid_cells": len(values)} if values else
        {"min": None, "max": None, "valid_cells": 0}
        for side, values in profile["odds_ranges"].items()
    }
    profile["exclusions"] = exclusions
    profile["sources"] = used_sources
    profile["manifest_filename"] = Path(manifest["_manifest_path"]).name
    profile["manifest_sha256"] = manifest["_manifest_sha256"]
    return accepted, profile


def multiclass_metrics(probabilities: list[tuple[float, float, float]], outcomes: list[int]) -> dict[str, Any]:
    if len(probabilities) != len(outcomes) or not outcomes:
        return {"n": len(outcomes), "multiclass_brier_score": None, "log_loss": None,
                "classification_accuracy": None, "hit_rate": None,
                "home_win_calibration": None, "home_win_hit_rate": None}
    briers = []
    losses = []
    correct = []
    home_probs = []
    home_outcomes = []
    for probs, outcome in zip(probabilities, outcomes):
        briers.append(sum((float(probs[i]) - (1.0 if i == outcome else 0.0)) ** 2 for i in range(3)))
        losses.append(-math.log(max(1e-12, min(1.0, float(probs[outcome])))))
        correct.append(max(range(3), key=lambda i: probs[i]) == outcome)
        home_probs.append(float(probs[0]))
        home_outcomes.append(outcome == 0)
    calibration = []
    bins = ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0000001))
    for lower, upper in bins:
        values = [(p, o) for p, o in zip(home_probs, home_outcomes) if lower <= p < upper]
        if values:
            calibration.append({"lower": lower, "upper": upper, "n": len(values),
                                "mean_predicted_home_win": sum(p for p, _ in values) / len(values),
                                "observed_home_win_rate": sum(o for _, o in values) / len(values)})
    home_hits = [((p >= 0.5) == o) for p, o in zip(home_probs, home_outcomes)]
    return {
        "n": len(outcomes),
        "multiclass_brier_score": round(sum(briers) / len(briers), 6),
        "log_loss": round(sum(losses) / len(losses), 6),
        "classification_accuracy": round(sum(correct) / len(correct), 6),
        "hit_rate": round(sum(correct) / len(correct), 6),
        "home_win_calibration": calibration,
        "home_win_hit_rate": round(sum(home_hits) / len(home_hits), 6),
    }


def _normalise_probs(values: Iterable[Any]) -> Optional[tuple[float, float, float]]:
    try:
        probs = tuple(float(v) for v in values)
    except (TypeError, ValueError, OverflowError):
        return None
    if len(probs) != 3 or any(not math.isfinite(v) or v < 0 for v in probs):
        return None
    total = sum(probs)
    if total <= 0:
        return None
    return tuple(v / total for v in probs)


def _market_probs(row: MatchRecord) -> Optional[tuple[float, float, float]]:
    if row.odds_h is None or row.odds_d is None or row.odds_a is None:
        return None
    return _normalise_probs((1 / row.odds_h, 1 / row.odds_d, 1 / row.odds_a))


def _fusion_probs(model: tuple[float, float, float], market: tuple[float, float, float], beta: float) -> tuple[float, float, float]:
    # Apply the project's logit shrinkage independently to the three outcomes,
    # then normalize to a valid multinomial distribution. This explicit final
    # normalization is a research protocol choice, not a production code change.
    eps = 1e-12
    logits = []
    for m, q in zip(model, market):
        m = min(1 - eps, max(eps, m))
        q = min(1 - eps, max(eps, q))
        logits.append(math.log(q / (1 - q)) + beta * (math.log(m / (1 - m)) - math.log(q / (1 - q))))
    exps = [math.exp(max(-700.0, min(700.0, value))) for value in logits]
    total = sum(exps)
    return tuple(value / total for value in exps)


def _fit_predict(train_rows: list[MatchRecord], test_rows: list[MatchRecord], cutoff: date,
                 xi: float, *, model_factory: Optional[Callable[..., Any]] = None,
                 weights_func: Optional[Callable[..., Any]] = None) -> tuple[dict[tuple[str, str, str, str], tuple[float, float, float]], dict[str, Any]]:
    model_factory = model_factory or pb.models.DixonColesGoalModel
    weights_func = weights_func or pb.models.dixon_coles_weights
    train = [row for row in train_rows if row.match_date < cutoff]
    train.sort(key=lambda row: (row.match_date, row.home_key, row.away_key))
    if len(train) < MIN_TRAIN_MATCHES:
        return {}, {"fit_status": "INSUFFICIENT_TRAINING", "train_matches": len(train), "max_train_date":
                    max((row.match_date for row in train), default=None)}
    appearances: dict[str, int] = {}
    for row in train:
        appearances[row.home_key] = appearances.get(row.home_key, 0) + 1
        appearances[row.away_key] = appearances.get(row.away_key, 0) + 1
    cold = [row for row in test_rows if min(appearances.get(row.home_key, 0), appearances.get(row.away_key, 0)) < MIN_TEAM_APPEARANCES]
    weights_dates = [row.match_date for row in train]
    try:
        weights = weights_func(weights_dates, xi=xi, base_date=cutoff)
        model = model_factory(
            [row.home_goals for row in train], [row.away_goals for row in train],
            [row.home_key for row in train], [row.away_key for row in train], weights=weights)
        model.fit()
    except Exception as exc:
        return {}, {"fit_status": "FIT_ERROR", "fit_error": f"{type(exc).__name__}: {exc}",
                    "train_matches": len(train), "max_train_date": max(row.match_date for row in train),
                    "cold_start_rows": len(cold)}
    predictions: dict[tuple[str, str, str, str], tuple[float, float, float]] = {}
    prediction_errors = 0
    cold_keys = {row.row_key for row in cold}
    for row in test_rows:
        if row.row_key in cold_keys:
            continue
        try:
            pred = model.predict(row.home_key, row.away_key)
            probs = _normalise_probs((pred.home_win, pred.draw, pred.away_win))
            if probs is None:
                prediction_errors += 1
                continue
            predictions[row.row_key] = probs
        except Exception:
            prediction_errors += 1
    return predictions, {
        "fit_status": "OK", "xi": xi, "train_matches": len(train),
        "max_train_date": max(row.match_date for row in train).isoformat(),
        "cutoff_exclusive": cutoff.isoformat(), "cold_start_rows": len(cold),
        "low_history_rows": sum(1 for row in test_rows if min(appearances.get(row.home_key, 0), appearances.get(row.away_key, 0)) < 15),
        "prediction_errors": prediction_errors,
    }


def _score_decisions(rows: list[dict[str, Any]], probability_field: str, min_ev: float = ROI_MIN_EV,
                     *, all_match_top_probability: bool = False) -> dict[str, Any]:
    decisions = []
    excluded_missing_probability = 0
    excluded_incomplete_or_invalid_prices = 0
    for row in rows:
        probs = row.get(probability_field)
        odds = row.get("market_odds")
        outcome = row.get("outcome_idx")
        if (not isinstance(probs, (list, tuple)) or len(probs) != 3
                or any(not isinstance(p, (int, float)) or isinstance(p, bool)
                       or not math.isfinite(float(p)) or not 0 <= float(p) <= 1 for p in probs)):
            excluded_missing_probability += 1
            continue
        if (not isinstance(odds, (list, tuple)) or len(odds) != 3
                or any(not isinstance(price, (int, float)) or isinstance(price, bool)
                       or not math.isfinite(float(price)) or float(price) <= 1 for price in odds)):
            excluded_incomplete_or_invalid_prices += 1
            continue
        if type(outcome) is not int or outcome not in {0, 1, 2}:
            continue
        evs = [float(probs[i]) * float(odds[i]) - 1 for i in range(3)]
        selected = (max(range(3), key=lambda i: (float(probs[i]), -i))
                    if all_match_top_probability else max(range(3), key=lambda i: (evs[i], -i)))
        if all_match_top_probability or evs[selected] >= min_ev:
            net = float(odds[selected]) - UNIT_STAKE if selected == outcome else -UNIT_STAKE
            decisions.append(net)
    n = len(decisions)
    total_stake = n * UNIT_STAKE
    return {"decisions": n, "unique_games": n, "candidate_unique_games": len(rows),
            "excluded_missing_probability": excluded_missing_probability,
            "excluded_incomplete_or_invalid_prices": excluded_incomplete_or_invalid_prices,
            "cohort": "events with this probability vector, final outcome and all three executable B365 prices",
            "selection_rule": ("one top-probability outcome per eligible match; fixed unit stake"
                               if all_match_top_probability else
                               "highest probability-times-B365-price EV per match; select only when estimated EV meets threshold"),
            "unit_stake": UNIT_STAKE,
            "minimum_model_ev": None if all_match_top_probability else min_ev,
            "net_units": round(sum(decisions), 4),
            "roi_pct": round(sum(decisions) / total_stake * 100, 4) if total_stake else None,
            "scope_note": "External historical bookmaker-price simulation only; not Taiwan lottery ROI."}


def _paired_block_bootstrap(common: list[dict[str, Any]], model_fields: dict[str, str],
                            *, replicates: int = BOOTSTRAP_REPLICATES, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Paired calendar-month block bootstrap deltas against normalized B365 probabilities."""
    blocks: dict[str, list[dict[str, Any]]] = {}
    for row in common:
        blocks.setdefault(str(row["date"])[:7], []).append(row)
    if len(blocks) < 2 or not common:
        return {"status": "INSUFFICIENT_BLOCKS", "block_unit": "calendar month", "block_count": len(blocks),
                "replicates": replicates, "comparisons": {}}
    keys = sorted(blocks)
    rng = random.Random(seed)

    def metric_pair(rows: list[dict[str, Any]], field: str, metric: str) -> Optional[float]:
        model_probs = [tuple(float(v) for v in row[field]) for row in rows]
        market_probs = [tuple(float(v) for v in row["market_normalized_hda_probs"]) for row in rows]
        outcomes = [int(row["outcome_idx"]) for row in rows]
        if metric in {"brier", "log_loss", "hit_rate"}:
            model_metric = multiclass_metrics(model_probs, outcomes)
            market_metric = multiclass_metrics(market_probs, outcomes)
            key = {"brier": "multiclass_brier_score", "log_loss": "log_loss", "hit_rate": "hit_rate"}[metric]
            a, b = model_metric.get(key), market_metric.get(key)
            return float(a) - float(b) if a is not None and b is not None else None
        model_roi = _score_decisions(rows, field, all_match_top_probability=True).get("roi_pct")
        market_roi = _score_decisions(rows, "market_normalized_hda_probs", all_match_top_probability=True).get("roi_pct")
        return float(model_roi) - float(market_roi) if model_roi is not None and market_roi is not None else None

    result = {}
    for name, field in model_fields.items():
        draws: dict[str, list[float]] = {metric: [] for metric in ("brier", "log_loss", "hit_rate", "paired_top_probability_roi_pct")}
        for _ in range(replicates):
            sampled = [row for key in (rng.choice(keys) for _ in keys) for row in blocks[key]]
            for metric in draws:
                delta = metric_pair(sampled, field, metric)
                if delta is not None and math.isfinite(delta):
                    draws[metric].append(delta)
        observed = {"brier": metric_pair(common, field, "brier"),
                    "log_loss": metric_pair(common, field, "log_loss"),
                    "hit_rate": metric_pair(common, field, "hit_rate"),
                    "paired_top_probability_roi_pct": metric_pair(common, field, "paired_top_probability_roi_pct")}
        ci = {}
        for metric, values in draws.items():
            ordered = sorted(values)
            lo = ordered[int(0.025 * (len(ordered) - 1))] if ordered else None
            hi = ordered[int(0.975 * (len(ordered) - 1))] if ordered else None
            ci[metric] = {"model_minus_market": observed[metric], "ci_95_low": lo, "ci_95_high": hi,
                          "valid_replicates": len(ordered)}
        result[name] = ci
    return {"status": "COMPLETED", "block_unit": "calendar month", "block_count": len(blocks),
            "replicates": replicates, "seed": seed,
            "interpretation": "Paired within the same resampled calendar-month blocks and match cohort; Brier/log-loss lower is better, hit rate/ROI higher is better.",
            "comparisons": result}


def _evaluate_rows(rows: list[MatchRecord], probabilities: dict[str, dict[tuple[str, str, str, str], tuple[float, float, float]]],
                   train_rows: list[MatchRecord], split: str, model_xi: Optional[float] = None,
                   include_bootstrap: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output = []
    model_fields = {"raw_dixon_coles": "raw_dixon_coles_probs", "fusion_beta_0_65": "fusion_beta_0_65_probs",
                    "market_normalized_hda": "market_normalized_hda_probs",
                    "empirical_training_base": "empirical_training_base_probs"}
    for row in rows:
        asof_train = [item for item in train_rows if item.match_date < row.match_date]
        train_outcomes = [item.outcome for item in asof_train]
        counts = [train_outcomes.count(i) for i in range(3)]
        train_probs = _normalise_probs([count / len(train_outcomes) for count in counts]) if train_outcomes else None
        market = _market_probs(row)
        raw = probabilities.get("raw_dixon_coles", {}).get(row.row_key)
        fused = _fusion_probs(raw, market, DEFAULT_BETA_MODEL) if raw and market else None
        exclusions = []
        if raw is None:
            exclusions.append("MODEL_COLD_START_OR_PREDICTION_MISSING")
        if market is None:
            exclusions.append("INCOMPLETE_OR_INVALID_B365_HDA")
        output.append({
            "league": row.league, "season": row.season, "split": split,
            "event_key": ":".join(row.row_key),
            "model_name": "Penaltyblog Dixon-Coles; fused estimate; normalized B365 H/D/A; empirical training base",
            "model_version": getattr(pb, "__version__", "unknown"), "dixon_coles_xi": model_xi,
            "date": row.match_date.isoformat(), "prediction_cutoff_exclusive": row.match_date.isoformat(),
            "home_team": row.home_team, "away_team": row.away_team,
            "canonical_home_team": row.home_key, "canonical_away_team": row.away_key,
            "team_resolution": row.team_resolution, "source_filename": row.source_filename,
            "source_sha256": row.source_sha256, "source_row_number": row.source_row_number,
            "market_source_sha256": row.source_sha256,
            "max_train_date": max((item.match_date for item in asof_train), default=None).isoformat()
            if asof_train else None,
            "train_match_count": len(asof_train),
            "raw_dixon_coles_probs": raw, "fusion_beta_0_65_probs": fused,
            "market_normalized_hda_probs": market, "empirical_training_base_probs": train_probs,
            "market_odds": [row.odds_h, row.odds_d, row.odds_a],
            "outcome_idx": row.outcome, "outcome": ("HOME" if row.outcome == 0 else "DRAW" if row.outcome == 1 else "AWAY"),
            "final_score": f"{row.home_goals}-{row.away_goals}",
            "exclusion_reasons": exclusions,
            "exclusion_reason": ";".join(exclusions) if exclusions else None,
        })

    # Same-cohort comparison: every listed model must have a probability and
    # every event must have a full H/D/A bookmaker market baseline.
    common = [row for row in output if all(row.get(field) is not None for field in model_fields.values())]
    metrics: dict[str, Any] = {
        "split": split, "candidate_rows": len(output),
        "same_cohort_n_unique_games": len(common),
        "same_cohort": {},
        "coverage": {name: sum(row.get(field) is not None for row in output) for name, field in model_fields.items()},
        "excluded_missing_or_cold_start": sum(row["raw_dixon_coles_probs"] is None for row in output),
        "excluded_incomplete_market": sum(row["market_normalized_hda_probs"] is None for row in output),
        "roi_decision_rule": {"unit_stake": UNIT_STAKE, "minimum_model_ev": ROI_MIN_EV,
                              "one_highest_ev_selection_per_unique_game": True},
        "ev_threshold_roi": {name: _score_decisions(output, field) for name, field in model_fields.items()},
    }
    for name, field in model_fields.items():
        subset = common if name != "empirical_training_base" else common
        metrics["same_cohort"][name] = multiclass_metrics(
            [tuple(row[field]) for row in subset], [row["outcome_idx"] for row in subset])
    metrics["paired_top_probability_roi"] = {
        name: _score_decisions(common, field, all_match_top_probability=True)
        for name, field in model_fields.items()
    }
    if include_bootstrap:
        metrics["paired_block_bootstrap"] = _paired_block_bootstrap(common, model_fields)
    return metrics, output


def _predictions_for_split(rows: list[MatchRecord], history: list[MatchRecord], xi: float,
                           *, model_factory: Optional[Callable[..., Any]] = None,
                           weights_func: Optional[Callable[..., Any]] = None) -> tuple[dict[str, Any], dict[str, Any]]:
    by_date: dict[date, list[MatchRecord]] = {}
    for row in rows:
        by_date.setdefault(row.match_date, []).append(row)
    predictions: dict[tuple[str, str, str, str], tuple[float, float, float]] = {}
    fits = []
    for cutoff, same_day_rows in sorted(by_date.items()):
        train = [row for row in history if row.match_date < cutoff]
        day_predictions, fit_meta = _fit_predict(train, same_day_rows, cutoff, xi,
                                                 model_factory=model_factory, weights_func=weights_func)
        predictions.update(day_predictions)
        fits.append(fit_meta)
    return {"raw_dixon_coles": predictions}, {
        "fit_count": len(fits), "fit_errors": sum(meta.get("fit_status") == "FIT_ERROR" for meta in fits),
        "insufficient_training_cutoffs": sum(meta.get("fit_status") == "INSUFFICIENT_TRAINING" for meta in fits),
        "cold_start_rows": sum(meta.get("cold_start_rows", 0) for meta in fits),
        "prediction_errors": sum(meta.get("prediction_errors", 0) for meta in fits),
        "fit_details": fits,
    }


def run_validation(source_dir: Path, output_dir: Path, league: str, *,
                   warmup_season: str = "2324", validation_season: str = "2425", holdout_season: str = "2526",
                   xi_candidates: tuple[float, ...] = XI_CANDIDATES,
                   model_factory: Optional[Callable[..., Any]] = None,
                   weights_func: Optional[Callable[..., Any]] = None,
                   forward_snapshot_path: Optional[Path] = None) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if (output_dir / "summary.json").exists():
        raise FileExistsError(f"Historical validation artifacts are immutable; choose a new output directory: {output_dir}")
    if (warmup_season, validation_season, holdout_season) != ("2324", "2425", "2526"):
        raise ValueError("Frozen split must be warmup 2324, validation 2425, locked holdout 2526")
    if not xi_candidates or any(not math.isfinite(float(xi)) or float(xi) <= 0 for xi in xi_candidates):
        raise ValueError("xi_candidates must contain finite positive values")
    records, profile = load_validation_dataset(Path(source_dir), league)
    by_season = {season: [row for row in records if row.season == season] for season in SUPPORTED_SEASONS}
    warmup = by_season[warmup_season]
    validation = by_season[validation_season]
    holdout = by_season[holdout_season]

    validation_runs = []
    validation_predictions = {}
    for xi in xi_candidates:
        print(f"[{league}] validation walk-forward fit: xi={xi:g}", flush=True)
        predictions, fit_audit = _predictions_for_split(validation, warmup + validation, xi,
                                                        model_factory=model_factory, weights_func=weights_func)
        _, rows_out = _evaluate_rows(validation, predictions, warmup + validation, "validation", model_xi=xi)
        # The selected parameter score is evaluated only on raw Dixon predictions;
        # rows without a valid prediction are reported and excluded from the score.
        scored = [row for row in rows_out if row["raw_dixon_coles_probs"] is not None]
        metric = multiclass_metrics([tuple(row["raw_dixon_coles_probs"]) for row in scored],
                                    [row["outcome_idx"] for row in scored])
        validation_runs.append({"xi": xi, "metrics": metric, "fit_audit": fit_audit})
        validation_predictions[str(xi)] = (predictions, fit_audit)
    viable = [run for run in validation_runs if run["metrics"]["multiclass_brier_score"] is not None]
    selected_xi = min(viable, key=lambda run: (run["metrics"]["multiclass_brier_score"], run["xi"]))["xi"] if viable else XI_CANDIDATES[1]
    selected_validation_predictions, selected_validation_audit = validation_predictions[str(selected_xi)]

    print(f"[{league}] locked holdout walk-forward fit: selected xi={selected_xi:g}", flush=True)
    holdout_probabilities, holdout_audit = _predictions_for_split(holdout, warmup + validation + holdout, selected_xi,
                                                                 model_factory=model_factory, weights_func=weights_func)
    validation_metrics, validation_rows = _evaluate_rows(validation, selected_validation_predictions,
                                                         warmup + validation, "validation", model_xi=selected_xi,
                                                         include_bootstrap=True)
    holdout_metrics, holdout_rows = _evaluate_rows(holdout, holdout_probabilities,
                                                   warmup + validation + holdout, "holdout", model_xi=selected_xi,
                                                   include_bootstrap=True)
    # Enforce the date-only data cutoff: a game on the target date is never in training.
    for row in validation_rows + holdout_rows:
        if row["max_train_date"] is not None and row["max_train_date"] >= row["prediction_cutoff_exclusive"]:
            raise AssertionError(f"point-in-time leakage at {row['league']} {row['date']}")

    forward = _read_forward_snapshot_status(forward_snapshot_path)
    source_ids = sorted({item["sha256"] for item in profile["sources"]})
    summary = {
        "schema_version": VALIDATION_SCHEMA,
        "status": "COMPLETED_HISTORICAL_VALIDATION" if viable else "INSUFFICIENT_VALIDATION_DATA",
        "scope": "external_historical_research_not_Taiwan_forward_validation",
        "evaluation_scope": "HISTORICAL_POSTHOC_RESEARCH; locked 2025/26 holdout is now historical and must not be reused for parameter selection",
        "production_sport_validation_scope": PRODUCTION_VALIDATION_SCOPE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": league, "source_profile": profile,
        "protocol": {
            "warmup_season": warmup_season, "validation_season": validation_season,
            "locked_holdout_season": holdout_season, "holdout_used_for_parameter_selection": False,
            "prediction_cutoff": "strict match_date < prediction_date; all same-day results excluded",
            "penaltyblog_version": getattr(pb, "__version__", "unknown"),
            "decay_weight_base_date": "prediction_date cutoff via penaltyblog.models.dixon_coles_weights(base_date=cutoff)",
            "xi_candidates": list(xi_candidates), "selected_xi_from_validation_only": selected_xi,
            "production_fusion_beta": DEFAULT_BETA_MODEL,
            "fusion_method": "independent outcome logits shrunk toward normalized B365 H/D/A by beta=0.65, then normalized to sum 1",
            "market_baseline": "Football-Data.co.uk Bet365 B365H/B365D/B365A pre-closing odds per notes.txt; C-suffixed B365CH/B365CD/B365CA are closing odds and were not used; none are Taiwan accepted prices",
            "roi_strategy": {"unit_stake": UNIT_STAKE, "minimum_model_ev": ROI_MIN_EV,
                             "selection_rule": "one highest expected-value outcome per game",
                             "market_odds_used_as_price": True},
            "metric_sample_unit": "unique league/date/canonical-home/canonical-away match; one multiclass outcome per match",
            "calibration_bins": "home-win probability bins; hit-rate and calibration are descriptive, not calibrated quality claims",
            "strategy_version": STRATEGY_VERSION,
            "strategy_experiment_identity": build_experiment_identity(get_strategy_metadata())["experiment_id"],
            "source_file_sha256s": source_ids,
        },
        "splits": {
            "validation": {**validation_metrics, "fit_audit": selected_validation_audit},
            "locked_holdout": {**holdout_metrics, "fit_audit": holdout_audit},
        },
        "forward_product_validation": forward,
        "limitations": [
            "All model probabilities are uncalibrated estimates unless later established by independent forward evidence.",
            "Football-Data B365H/D/A are pre-closing bookmaker odds; C-suffixed fields are closing odds. Neither source is Taiwan lottery accepted pricing; simulated ROI does not establish Taiwan profitability.",
            "Only events with all four model/market probability vectors enter the same-cohort multiclass comparison.",
            "Paired confidence intervals resample calendar-month blocks on the same match cohort; the supported historical source scope currently covers only EPL and La Liga, not the full production sport set.",
            "Unmapped source team names are preserved as exact normalized source identities and reported; no fuzzy team inference is made.",
        ],
    }
    _write_outputs(output_dir, summary, validation_rows + holdout_rows)
    return summary


def _read_forward_snapshot_status(snapshot_path: Optional[Path]) -> dict[str, Any]:
    if snapshot_path is None:
        from core.research_paths import research_paths
        snapshot_path = research_paths()["snapshots"]
    path = Path(snapshot_path)
    if not path.exists():
        return {"status": "NOT_YET_VALIDATED", "snapshot_count": 0, "eligible_current_experiment_count": 0,
                "source_file": str(path), "source_file_sha256": None}
    raw = path.read_bytes()
    rows = []
    malformed = 0
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            malformed += 1
            continue
        if isinstance(item, dict):
            rows.append(item)
        else:
            malformed += 1
    from core.performance_metrics import PerformanceMetricsEngine
    cohort = PerformanceMetricsEngine.forward_cohort(rows)
    model_metrics = PerformanceMetricsEngine.evaluate_model_overall_metrics(rows, cohort["target_experiment_id"])
    current_eligible = model_metrics["sample_size"]
    return {"status": "READY_FOR_METRICS" if current_eligible else "NOT_YET_VALIDATED",
            "snapshot_count": len(rows), "eligible_current_experiment_count": current_eligible,
            "current_binary_observation_count": len(cohort["observations"]),
            "cohort_audit": cohort["audit"], "malformed_lines": malformed,
            "source_file": path.name, "source_file_sha256": _sha256(raw)}


def _write_outputs(output_dir: Path, summary: dict[str, Any], prediction_rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True,
                                                           default=lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v)),
                                               encoding="utf-8")
    jsonl = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                              default=lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v)) + "\n"
                    for row in prediction_rows)
    (output_dir / "predictions.jsonl").write_text(jsonl, encoding="utf-8")
    columns = sorted({key for row in prediction_rows for key in row})
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in prediction_rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict, tuple)) else value
                         for key, value in row.items()})
    (output_dir / "predictions.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    calibration_data = {split_name: {name: metric["home_win_calibration"]
                                     for name, metric in split["same_cohort"].items()}
                        for split_name, split in summary["splits"].items()}
    (output_dir / "calibration_plot_data.json").write_text(
        json.dumps(calibration_data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report = [
        f"# Historical model validation: {summary['league']}", "",
        "Status: NOT an in-product or Taiwan lottery profitability validation.", "",
        f"Training/validation/locked holdout: {summary['protocol']['warmup_season']} / "
        f"{summary['protocol']['validation_season']} / {summary['protocol']['locked_holdout_season']}",
        f"Validation-selected xi: {summary['protocol']['selected_xi_from_validation_only']}",
        f"Forward product validation: {summary['forward_product_validation']['status']} "
        f"(eligible current experiment snapshots: {summary['forward_product_validation']['eligible_current_experiment_count']})", "",
        "## Split metrics", "",
    ]
    for split_name, split in summary["splits"].items():
        report += [f"### {split_name}", "", f"Same-cohort unique games: {split['same_cohort_n_unique_games']}", "",
                   "| Model | N | Brier | Log loss | Hit rate | Home hit rate |",
                   "|---|---:|---:|---:|---:|---:|"]
        for name, metric in split["same_cohort"].items():
            report.append(f"| {name} | {metric['n']} | {metric['multiclass_brier_score']} | {metric['log_loss']} | "
                          f"{metric['hit_rate']} | {metric['home_win_hit_rate']} |")
        report += ["", "Paired ROI: same complete common cohort, one top-probability outcome per match, fixed one-unit stake for every probability source:", "",
                   "| Probability source | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |",
                   "|---|---:|---:|---:|---:|---:|---:|"]
        for name, score in split["paired_top_probability_roi"].items():
            roi = "N/A" if score["roi_pct"] is None else f"{score['roi_pct']:+.2f}%"
            report.append(f"| {name} | {score['candidate_unique_games']} | {score['decisions']} | "
                          f"{score['excluded_missing_probability']} | {score['excluded_incomplete_or_invalid_prices']} | "
                          f"{score['net_units']:+.2f} | {roi} |")
        report += ["", "Supplemental EV-threshold strategy: model selects the highest probability-times-B365-price EV only when estimated EV ≥5%; the market baseline tests its probabilities against its own prices and therefore has no positive-EV selection by construction:", "",
                   "| Price/probability strategy | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |",
                   "|---|---:|---:|---:|---:|---:|---:|"]
        for name, score in split["ev_threshold_roi"].items():
            roi = "N/A" if score["roi_pct"] is None else f"{score['roi_pct']:+.2f}%"
            report.append(f"| {name} | {score['candidate_unique_games']} | {score['decisions']} | "
                          f"{score['excluded_missing_probability']} | {score['excluded_incomplete_or_invalid_prices']} | "
                          f"{score['net_units']:+.2f} | {roi} |")
        report.append("")
        report.append("")
    report += ["", "## Paired calendar-month block bootstrap 95% CI", "",
               "Delta is model minus normalized B365 market on the same matches; Brier and Log loss lower is better, hit rate and ROI higher is better.", "",
               "| Split | Model | Metric | Delta | 95% CI | Valid draws |",
               "|---|---|---|---:|---:|---:|"]
    for split_name, split in summary["splits"].items():
        boot = split.get("paired_block_bootstrap", {})
        for model_name, values in boot.get("comparisons", {}).items():
            for metric_name, item in values.items():
                point = item.get("model_minus_market")
                lo, hi = item.get("ci_95_low"), item.get("ci_95_high")
                point_text = "N/A" if point is None else f"{point:+.4f}"
                ci_text = "N/A" if lo is None or hi is None else f"[{lo:+.4f}, {hi:+.4f}]"
                report.append(f"| {split_name} | {model_name} | {metric_name} | {point_text} | {ci_text} | {item.get('valid_replicates', 0)} |")
        report.append(f"Bootstrap blocks: {boot.get('block_count', 0)} calendar months; replicates: {boot.get('replicates', 0)}; seed: {boot.get('seed', 'N/A')}.")
    scope = summary.get("production_sport_validation_scope", {})
    report += ["", "## Production sport coverage", "",
               f"Validated historical leagues: {', '.join(scope.get('validated_external_leagues', [])) or 'none'}.",
               f"Unsupported production sports/leagues: {', '.join(scope.get('unsupported_production_sports', []))}.",
               scope.get("reason", "")]
    report += ["", "## Limitations", ""] + [f"- {item}" for item in summary["limitations"]]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
