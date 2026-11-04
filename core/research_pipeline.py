"""Isolated, resumable, wallet-free research polling pipeline.

The pipeline uses the same Taiwan odds adapter, prediction/parlay loggers, and
settlement rules as the interactive research path, while routing every write to
an explicit research data root. It never creates a shadow wallet manager.
"""
from __future__ import annotations

import json
import hashlib
import csv
import logging
import math
import os
import tempfile
import time
import uuid
from io import StringIO
from collections import Counter
from dataclasses import fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from core.bet_validation import assess_leg, event_key, parse_aware_time
from core.experiment_identity import get_current_experiment_identity
from core.odds_watcher import OddsWatcher
from core.parlay_engine import ParlayEngine
from core.research_reporting import ResearchReportMixin
from core.research_mlb import MLBResearchMixin
from core.research_helpers import (
    _json_default,
    _leg_from_payload,
    _leg_payload,
    _mlb_game_date,
    _mlb_game_is_cancelled,
    _mlb_game_is_final,
    _mlb_game_is_regular_or_postseason,
    _mlb_needs_live_reconciliation,
    _mlb_normalize_live_feed,
    _mlb_reschedule_target_date,
    _parse_football_data_date,
    _read_json,
    _write_json_atomic,
)
from core.shadow_parlay_logger import ShadowParlayLogger
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import get_strategy_metadata
from core.contracts.common import PredictionSignal, TaiwanLeg
from integrations.experts.playsport_crowd import PlaysportCrowdAdapter
from integrations.experts.playsport_expert import PlaysportExpertAdapter
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "research_pipeline.yaml"
PROTECTED_DATA_DIRS = ("cache", "historical", "wallet", "models", "snapshots", "source_health")


class _NoWallet:
    def get_recent_tickets(self, limit=200):
        return []


class ResearchPipeline(ResearchReportMixin, MLBResearchMixin):
    """Execute one cadence window of the isolated research pipeline."""

    def __init__(
        self,
        config_path: Path | str | None = None,
        data_root: Path | str | None = None,
        *,
        odds_adapter=None,
        signal_hub=None,
        result_engine=None,
        clock: Callable[[], datetime] | None = None,
        model_updater=None,
        soccer_data_fetcher=None,
    ):
        raw_config_path = Path(config_path or DEFAULT_CONFIG)
        self.config_path = (PROJECT_ROOT / raw_config_path).resolve() if not raw_config_path.is_absolute() else raw_config_path.resolve()
        self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        configured_root = data_root or self.config.get("data_root", "data/research_pipeline")
        from core.research_paths import resolve_research_data_root
        self.data_root = resolve_research_data_root(configured_root, self.config_path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._odds_adapter = odds_adapter
        self._signal_hub = signal_hub
        self._result_engine = result_engine
        self._model_updater = model_updater
        self._soccer_data_fetcher = soccer_data_fetcher

    def _validate_data_root(self) -> None:
        from core.research_paths import resolve_research_data_root
        self.data_root = resolve_research_data_root(self.data_root, self.config_path)

    def _window(self, now: datetime) -> tuple[str, datetime]:
        cadence = max(1, int(self.config.get("cadence_minutes", 15)))
        epoch = int(now.timestamp())
        start_epoch = epoch - epoch % (cadence * 60)
        start = datetime.fromtimestamp(start_epoch, timezone.utc)
        return start.strftime("%Y%m%dT%H%MZ"), start

    def _current_utc(self) -> datetime:
        current = self.clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Pipeline clock must return a timezone-aware datetime.")
        return current.astimezone(timezone.utc)

    def _components(self):
        from core.research_paths import research_paths
        from core.model_acceptance import ModelAcceptanceGate
        from core.model_registry import ModelRegistry
        paths = research_paths(self.data_root, self.config_path)
        if self._odds_adapter is None:
            from core.scraper import PlaysportScraper
            scraper = PlaysportScraper(
                cache_dir=self.data_root / "cache" / "playsport",
                snapshot_dir=self.data_root / "snapshots",
                source_health_history_path=paths["source_health"],
            )
            self._odds_adapter = PlaysportOddsAdapter(scraper=scraper)
        if self._signal_hub is None:
            # Real configured models run with their cache/state redirected into
            # this research root; acceptance reads the same isolated ledger.
            gate = ModelAcceptanceGate(snapshot_path=paths["snapshots"])
            scraper = getattr(self._odds_adapter, "scraper", None)
            if scraper is None:
                from core.scraper import PlaysportScraper
                scraper = PlaysportScraper(
                    cache_dir=self.data_root / "cache" / "playsport_experts",
                    snapshot_dir=self.data_root / "snapshots",
                    source_health_history_path=paths["source_health"],
                )
            self._initialize_elo_checkpoint()
            registry = ModelRegistry(data_root=self.data_root, acceptance_gate=gate)
            self._signal_hub = SignalHub(
                expert_adapter=PlaysportExpertAdapter(scraper=scraper),
                crowd_adapter=PlaysportCrowdAdapter(),
                model_registry=registry,
            )
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.snapshot_logger = PredictionSnapshotLogger(paths["snapshots"])
        self.parlay_logger = ShadowParlayLogger(paths["parlays"])
        self.odds_watcher = OddsWatcher(paths["odds"])
        self.parlay_engine = ParlayEngine(signal_hub=self._signal_hub)
        if self._result_engine is None:
            from core.settlement_engine import SettlementEngine
            self._result_engine = SettlementEngine(
                snapshot_logger=self.snapshot_logger,
                parlay_logger=self.parlay_logger,
                shadow_portfolio=_NoWallet(),
                odds_watcher=self.odds_watcher,
            )
        else:
            # Injected result providers are supported, but all persistence and
            # wallet access still bind to isolated research implementations.
            self._result_engine.snapshot_logger = self.snapshot_logger
            self._result_engine.parlay_logger = self.parlay_logger
            self._result_engine.shadow_portfolio = _NoWallet()
            self._result_engine.odds_watcher = self.odds_watcher
        return self._odds_adapter, self._signal_hub

    def _initialize_elo_checkpoint(self) -> dict[str, Any]:
        """Import an already initialized official Elo checkpoint once, read-only."""
        settings = self.config.get("model_update", {}) or {}
        if not settings.get("seed_existing_official_checkpoint", True):
            return {"status": "SKIPPED", "reason": "checkpoint import disabled"}
        from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter, STATE_FILE
        destination = self.data_root / "model_state" / "live_mlb_elo.json"
        receipt = self.data_root / "state" / "elo_checkpoint_import.json"
        if destination.exists():
            return _read_json(receipt, {"status": "EXISTING_ISOLATED_CHECKPOINT"})
        source = Path(STATE_FILE)
        if not source.exists():
            return {"status": "NO_CHECKPOINT", "reason": "official initialized state not present"}
        adapter = LiveMLBEloAdapter(state_file=source)
        if not adapter._has_state or adapter._load_error or not adapter.data_as_of:
            return {"status": "UNTRUSTED_CHECKPOINT", "reason": "state is uninitialized, invalid, or missing data_as_of"}
        if "mlb stats api" not in str(adapter.source or "").casefold():
            return {"status": "UNTRUSTED_CHECKPOINT", "reason": "checkpoint source is not identified as MLB Stats API"}
        data = source.read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        from core.persistence import atomic_write_bytes
        atomic_write_bytes(destination, data)
        metadata = {"status": "IMPORTED", "source_sha256": hashlib.sha256(data).hexdigest(),
                    "data_as_of": adapter.data_as_of, "source_label": adapter.source,
                    "source_path": str(source), "destination_path": str(destination),
                    "imported_at_utc": self.clock().astimezone(timezone.utc).isoformat()}
        _write_json_atomic(receipt, metadata)
        return metadata

    class _Lock:
        def __init__(self, path: Path):
            self.path, self.stream = path, None
        def __enter__(self):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.stream = open(self.path, "a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    self.stream.seek(0, os.SEEK_END)
                    if self.stream.tell() == 0:
                        self.stream.write(b"\0")
                        self.stream.flush()
                    self.stream.seek(0)
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self.stream.close()
                raise RuntimeError("另一個研究排程仍在執行。") from exc
            return self
        def __exit__(self, *_):
            if self.stream:
                if os.name == "nt":
                    import msvcrt
                    self.stream.seek(0)
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
                self.stream.close()

    def run(self, *, dry_run: bool = False, resume: bool = False) -> dict[str, Any]:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Pipeline clock must return a timezone-aware datetime.")
        now = now.astimezone(timezone.utc)
        self._validate_data_root()
        window_id, window_start = self._window(now)
        plan = {
            "cadence_minutes": int(self.config.get("cadence_minutes", 15)),
            "run_window_id": window_id,
            "window_start_utc": window_start.isoformat(),
            "data_root": str(self.data_root),
            "stages": ["model_update", "soccer_model_update", "source_fetch_health", "pregame_snapshots", "odds_observations",
                       "parlay_candidates", "multi_sport_settlement", "weekly_report"],
            "network_enabled": not dry_run,
            "mutations_enabled": not dry_run,
        }
        if dry_run:
            return {"status": "DRY_RUN", "plan": plan}

        log_path = self.data_root / "logs" / "research_pipeline.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not any(getattr(handler, "baseFilename", None) == str(log_path) for handler in logger.handlers):
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        logger.info("Starting research pipeline window %s", window_id)

        run_dir = self.data_root / "runs" / window_id
        state_path = run_dir / "run.json"
        with self._Lock(self.data_root / "locks" / "pipeline.lock"):
            state = _read_json(state_path, None)
            if state is None and resume:
                cutoff = now - timedelta(minutes=max(1, int(self.config.get("resume_max_age_minutes", 60))))
                max_attempts = max(1, int(self.config.get("max_attempts_per_stage", 3)))
                candidates = []
                for candidate_path in (self.data_root / "runs").glob("*/run.json"):
                    candidate = _read_json(candidate_path, None)
                    if not isinstance(candidate, dict) or candidate.get("status") not in {"FAILED", "RUNNING"}:
                        continue
                    stage_states = candidate.get("stages") or {}
                    retryable = any(
                        stage.get("status") == "RUNNING" and int(stage.get("attempts", 0)) < max_attempts
                        or stage.get("status") == "FAILED" and int(stage.get("attempts", 0)) < max_attempts
                        for stage in stage_states.values() if isinstance(stage, dict)
                    )
                    if stage_states and not retryable:
                        continue
                    started = parse_aware_time(candidate.get("started_at"))
                    if started and cutoff <= started <= now:
                        candidates.append((started, candidate_path, candidate))
                if candidates:
                    _, state_path, state = max(candidates, key=lambda item: item[0])
                    run_dir = state_path.parent
                    window_id = str(state.get("run_window_id") or run_dir.name)
                    window_start = parse_aware_time(state.get("window_start_utc")) or window_start
                    state["resume_count"] = int(state.get("resume_count", 0)) + 1
            if state and state.get("status") == "COMPLETE":
                return {"status": "COMPLETE", "run_id": state["run_id"], "run_window_id": window_id,
                        "duplicate_window": True, "stages": state["stages"]}
            if state is None:
                state = {"schema": 1, "run_id": uuid.uuid4().hex, "run_window_id": window_id,
                         "window_start_utc": window_start.isoformat(), "started_at": now.isoformat(),
                         "status": "RUNNING", "stages": {}, "experiment_identity": get_current_experiment_identity(),
                         "strategy_metadata": get_strategy_metadata()}
            state["status"] = "RUNNING"
            _write_json_atomic(state_path, state)
            self._components()
            stage_data = run_dir / "data"
            stage_data.mkdir(parents=True, exist_ok=True)
            stage_functions = [
                ("model_update", lambda: self._stage_model_update(stage_data)),
                ("soccer_model_update", lambda: self._stage_soccer_model_update(stage_data)),
                ("source_fetch_health", lambda: self._stage_source(window_id, now, stage_data)),
                ("pregame_snapshots", lambda: self._stage_snapshots(window_id, self._current_utc(), stage_data)),
                ("odds_observations", lambda: self._stage_observations(window_id, stage_data)),
                ("parlay_candidates", lambda: self._stage_parlays(window_id, state["run_id"], stage_data)),
                ("multi_sport_settlement", lambda: self._stage_settlement(stage_data)),
                ("weekly_report", lambda: self._stage_report(stage_data)),
            ]
            max_attempts = max(1, int(self.config.get("max_attempts_per_stage", 3)))
            try:
                for name, function in stage_functions:
                    if name in {"pregame_snapshots", "odds_observations", "parlay_candidates"} and state["stages"].get("source_fetch_health", {}).get("status") != "SUCCEEDED":
                        state["stages"][name] = {"status": "BLOCKED", "attempts": 0,
                                                 "error": "Fresh source stage failed; dependent observation not attempted."}
                        continue
                    existing = state["stages"].get(name, {})
                    if existing.get("status") in {"SUCCEEDED", "SKIPPED"}:
                        continue
                    attempts = int(existing.get("attempts", 0))
                    if attempts >= max_attempts:
                        state["stages"][name]["status"] = "FAILED"
                        state["stages"][name]["error"] = f"stage {name} reached bounded retry limit ({max_attempts})"
                        continue
                    entry = {"status": "RUNNING", "attempts": attempts + 1,
                             "started_at": self.clock().astimezone(timezone.utc).isoformat()}
                    state["stages"][name] = entry
                    _write_json_atomic(state_path, state)
                    try:
                        result = function()
                        entry.update(status=result.pop("_stage_status", "SUCCEEDED"), result=result,
                                     completed_at=self.clock().astimezone(timezone.utc).isoformat())
                    except Exception as exc:
                        entry.update(status="FAILED", error=f"{type(exc).__name__}: {exc}",
                                     completed_at=self.clock().astimezone(timezone.utc).isoformat())
                        _write_json_atomic(state_path, state)
                        continue
                    _write_json_atomic(state_path, state)
                failed_stages = [name for name, entry in state["stages"].items()
                                 if entry.get("status") in {"FAILED", "BLOCKED"}]
                if failed_stages:
                    raise RuntimeError("Incomplete research stages: " + ", ".join(failed_stages))
                state["status"] = "COMPLETE"
                state.pop("error", None)
            except Exception as exc:
                logger.exception("Research pipeline run %s failed", state.get("run_id"))
                state["status"] = "FAILED"
                state["error"] = f"{type(exc).__name__}: {exc}"
                state["updated_at"] = self.clock().astimezone(timezone.utc).isoformat()
                _write_json_atomic(state_path, state)
                self._record_operation_alerts(run_dir, state_path, state)
                return {"status": "FAILED", "run_id": state["run_id"], "run_window_id": window_id,
                        "error": state["error"], "stages": state["stages"]}
            state["completed_at"] = self.clock().astimezone(timezone.utc).isoformat()
            _write_json_atomic(state_path, state)
            logger.info("Completed research pipeline run %s window %s", state["run_id"], window_id)
            self._record_operation_alerts(run_dir, state_path, state)
            return {"status": state["status"], "run_id": state["run_id"], "run_window_id": window_id,
                    "stages": state["stages"]}

    def _record_operation_alerts(self, run_dir, state_path, state):
        try:
            from core.research_health import build_research_health
            from core.research_alerts import record_health_alerts
            result = record_health_alerts(build_research_health(self.data_root), self.data_root,
                desktop_notifications=bool(self.config.get("desktop_notifications", False)))
            _write_json_atomic(run_dir / "data/operations_alerts.json", result)
        except Exception as exc:
            state["operations_alert_error"] = f"{type(exc).__name__}: {exc}"
            _write_json_atomic(state_path, state)

    def _stage_source(self, window_id: str, now: datetime, stage_data: Path) -> dict[str, Any]:
        adapter = self._odds_adapter
        alliances = [str(value) for value in self.config.get("alliances", ["1", "4", "93", "6", "2", "9", "3", "7"])]
        legs = adapter.get_taiwan_legs(alliances, force_refresh=bool(self.config.get("force_refresh", True)))
        health_getter = getattr(adapter, "get_source_status", None)
        health = health_getter() if callable(health_getter) else {}
        _write_json_atomic(stage_data / "source_health.json", health)
        _write_json_atomic(stage_data / "source_legs.json", [_leg_payload(leg) for leg in legs])
        source_errors = [{"alliance_id": aid, "source_status": row.get("source_status"),
                          "failure_status": row.get("failure_status"), "error": row.get("error"),
                          "source_url": row.get("source_url")}
                         for aid, row in health.items()
                         if isinstance(row, dict) and (row.get("failure_status") or row.get("error"))]
        hard_failures = [row for row in health.values() if isinstance(row, dict) and
                         (row.get("failure_status") or row.get("source_status") in {"UNAVAILABLE", "FETCH_ERROR", "HTTP_ERROR"})]
        if not legs and health and len(hard_failures) == len(health):
            raise RuntimeError("盤口來源全部無資料且來源狀態有抓取失敗")
        return {"alliance_count": len(alliances), "fetched_leg_count": len(legs),
                "source_status_counts": dict(Counter(str((row or {}).get("source_status", "UNKNOWN"))
                                                      for row in health.values())),
                "confirmed_no_event_source_count": sum(
                    1 for row in health.values() if isinstance(row, dict)
                    and row.get("source_status") == "LIVE_NO_EVENTS"
                    and row.get("no_events_confirmed") is True
                    and not row.get("failure_status")
                ),
                "source_error_count": len(source_errors), "source_errors": source_errors,
                "health_path": str(stage_data / "source_health.json")}

    def _window_legs(self, window_id: str, now: datetime, stage_data: Path, *, lead_minutes: int | None = None):
        lead = max(1, int(lead_minutes if lead_minutes is not None
                          else self.config.get("pregame_lead_minutes", 60)))
        deadline = now + timedelta(minutes=lead)
        raw = _read_json(stage_data / "source_legs.json", [])
        selected, excluded = [], Counter()
        for payload in raw:
            leg = _leg_from_payload(payload)
            start = parse_aware_time(leg.start_time_utc)
            if start is None:
                excluded["START_TIME_UNKNOWN"] += 1
                continue
            if start <= now:
                excluded["EVENT_STARTED"] += 1
                continue
            if start > deadline:
                excluded["OUTSIDE_LEAD_WINDOW"] += 1
                continue
            checks = assess_leg(leg, now=now)
            if not checks["is_ready"]:
                excluded.update(checks["reasons"])
                continue
            leg.signal_evidence["observation_window_id"] = window_id
            selected.append(leg)
        return selected, excluded

    @staticmethod
    def _research_option_key(leg: TaiwanLeg) -> tuple[str, str, str, str, str]:
        return (event_key(leg), str(leg.market or ""), str(getattr(leg, "side", "") or ""),
                str(getattr(leg, "line", "") or ""), str(leg.selection or ""))

    @staticmethod
    def _has_raw_model_prediction(leg: TaiwanLeg) -> bool:
        predictions = (leg.signal_evidence or {}).get("model_candidate_provenances", [])
        if not isinstance(predictions, list):
            return False
        for prediction in predictions:
            if not isinstance(prediction, dict):
                continue
            try:
                probability = float(prediction.get("raw_probability"))
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(probability) and 0.0 < probability < 1.0:
                return True
        return False

    @staticmethod
    def _model_prediction_coverage(legs: list[TaiwanLeg], now: datetime) -> dict[str, Any]:
        prediction_count = 0
        valid_prediction_count = 0
        event_keys: set[str] = set()
        model_event_pairs: set[tuple[str, str]] = set()
        valid_event_keys: set[str] = set()
        freshness_counts = Counter()

        for leg in legs:
            key = event_key(leg)
            start = parse_aware_time(leg.start_time_utc)
            predictions = (leg.signal_evidence or {}).get("model_candidate_provenances", [])
            if not isinstance(predictions, list):
                continue
            for prediction in predictions:
                if not isinstance(prediction, dict):
                    continue
                probability = prediction.get("raw_probability")
                try:
                    probability = float(probability)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(probability) or not 0.0 < probability < 1.0:
                    continue

                prediction_count += 1
                freshness = str(prediction.get("freshness_status") or "UNKNOWN").upper()
                freshness_counts[freshness] += 1
                model_id = str(prediction.get("model_id") or prediction.get("source_id") or "UNKNOWN")
                if key:
                    event_keys.add(key)
                    model_event_pairs.add((key, model_id))

                as_of = parse_aware_time(prediction.get("data_as_of"))
                if as_of is None:
                    # Penaltyblog's point-in-time training watermark is a date
                    # because the source does not publish match timestamps.
                    raw_as_of = str(prediction.get("data_as_of") or "")
                    try:
                        parsed_date = datetime.fromisoformat(raw_as_of)
                    except (TypeError, ValueError):
                        parsed_date = None
                    if parsed_date is not None and parsed_date.tzinfo is None and len(raw_as_of) == 10:
                        as_of = parsed_date.replace(tzinfo=timezone.utc)

                point_in_time_verified = (
                    prediction.get("point_in_time_status") == "VALID"
                    or prediction.get("point_in_time_verified") is True
                    or prediction.get("pre_event_source_order_valid") is True
                )
                if (freshness in {"LIVE", "FRESH", "AGING"} and as_of is not None
                        and as_of <= now and start is not None and as_of < start
                        and point_in_time_verified):
                    valid_prediction_count += 1
                    if key:
                        valid_event_keys.add(key)

        return {
            "raw_model_prediction_count": prediction_count,
            "raw_model_prediction_event_count": len(event_keys),
            "unique_model_event_pair_count": len(model_event_pairs),
            "data_valid_model_prediction_count": valid_prediction_count,
            "data_valid_model_event_count": len(valid_event_keys),
            "model_data_freshness_status_counts": dict(freshness_counts),
            "data_valid_event_keys": valid_event_keys,
        }

    @staticmethod
    def _source_window_coverage(raw_legs: list[dict[str, Any]], now: datetime, lead_minutes: int) -> dict[str, int]:
        events: set[str] = set()
        options: set[tuple[str, str, str, str, str]] = set()
        deadline = now + timedelta(minutes=max(1, int(lead_minutes)))
        for row in raw_legs:
            if not isinstance(row, dict):
                continue
            leg = _leg_from_payload(row)
            start = parse_aware_time(leg.start_time_utc)
            key = event_key(leg)
            if not key or start is None or start <= now or start > deadline:
                continue
            events.add(key)
            options.add(ResearchPipeline._research_option_key(leg))
        return {"source_event_count": len(events), "source_option_count": len(options)}

    def _stage_snapshots(self, window_id: str, now: datetime, stage_data: Path) -> dict[str, Any]:
        # A resumed stage can run long after the source stage completed. Use the
        # wall clock at eligibility time so old cached quotes cannot be sealed.
        now = self._current_utc()
        formal_lead = max(1, int(self.config.get("pregame_lead_minutes", 60)))
        shadow_lead = max(formal_lead, int(self.config.get("shadow_pregame_lead_minutes", formal_lead)))
        selected, excluded = self._window_legs(window_id, now, stage_data, lead_minutes=formal_lead)
        shadow_window_legs, shadow_excluded = self._window_legs(
            window_id, now, stage_data, lead_minutes=shadow_lead
        )
        formal_option_keys = {self._research_option_key(leg) for leg in selected}
        shadow_only = [leg for leg in shadow_window_legs
                       if self._research_option_key(leg) not in formal_option_keys]

        enriched = [self._signal_hub.evaluate_taiwan_leg(leg) for leg in selected]
        shadow_enriched = [self._signal_hub.evaluate_taiwan_leg(leg) for leg in shadow_only]
        for leg in enriched:
            leg.signal_evidence["observation_window_id"] = window_id
            leg.signal_evidence["observation_scope"] = "FORMAL_QUALIFICATION_WINDOW"
        shadow_window_id = f"{window_id}:shadow-{shadow_lead}m"
        for leg in shadow_enriched:
            leg.signal_evidence["observation_window_id"] = shadow_window_id
            leg.signal_evidence["observation_scope"] = "SHADOW_ONLY"
        snapshots = self.snapshot_logger.log_batch(enriched, observation_window_id=window_id)
        shadow_prediction_legs = [leg for leg in shadow_enriched if self._has_raw_model_prediction(leg)]
        shadow_snapshots = self.snapshot_logger.log_batch(
            shadow_prediction_legs, observation_window_id=shadow_window_id
        )
        for leg, snapshot in zip(enriched, snapshots):
            leg.signal_evidence["snapshot_id"] = snapshot.get("snapshot_id")
            leg.signal_evidence["forward_validation_eligible"] = snapshot.get("forward_validation_eligible")
        _write_json_atomic(stage_data / "selected_legs.json", [_leg_payload(leg) for leg in enriched])
        _write_json_atomic(stage_data / "snapshot_ids.json", [row.get("snapshot_id") for row in snapshots])
        formal_predictions = self._model_prediction_coverage(enriched, now)
        shadow_predictions = self._model_prediction_coverage(shadow_enriched, now)
        all_window_predictions = self._model_prediction_coverage(enriched + shadow_enriched, now)
        formal_predictions.pop("data_valid_event_keys")
        shadow_prediction_events = shadow_predictions.pop("data_valid_event_keys")
        shadow_window_prediction_events = all_window_predictions.pop("data_valid_event_keys")

        raw_legs = _read_json(stage_data / "source_legs.json", [])
        formal_source_coverage = self._source_window_coverage(raw_legs, now, formal_lead)
        shadow_source_coverage = self._source_window_coverage(raw_legs, now, shadow_lead)
        shadow_sharp_events = {
            event_key(leg) for leg in shadow_enriched
            if (leg.signal_evidence or {}).get("market_source_qualification") == "SHARP_QUALIFIED"
            and not (leg.signal_evidence or {}).get("is_market_synthetic")
            and event_key(leg)
        }
        shadow_international_events = {
            event_key(leg) for leg in shadow_enriched
            if (leg.signal_evidence or {}).get("international_market_complete") is True
            and not (leg.signal_evidence or {}).get("is_market_synthetic")
            and event_key(leg)
        }
        all_window_sharp_events = {
            event_key(leg) for leg in enriched + shadow_enriched
            if (leg.signal_evidence or {}).get("market_source_qualification") == "SHARP_QUALIFIED"
            and not (leg.signal_evidence or {}).get("is_market_synthetic")
            and event_key(leg)
        }
        all_window_international_events = {
            event_key(leg) for leg in enriched + shadow_enriched
            if (leg.signal_evidence or {}).get("international_market_complete") is True
            and not (leg.signal_evidence or {}).get("is_market_synthetic")
            and event_key(leg)
        }
        shadow_coverage = {
            "formal_window_minutes": formal_lead,
            "shadow_window_minutes": shadow_lead,
            "formal_window": {**formal_source_coverage,
                              "eligible_event_count": len({event_key(leg) for leg in enriched if event_key(leg)}),
                              "eligible_option_count": len(enriched),
                              "excluded_option_reasons": dict(excluded)},
            "shadow_window": {**shadow_source_coverage,
                              "eligible_event_count": len({event_key(leg) for leg in enriched + shadow_enriched if event_key(leg)}),
                              "eligible_option_count": len(enriched) + len(shadow_enriched),
                              "shadow_only_event_count": len({event_key(leg) for leg in shadow_enriched if event_key(leg)}),
                              "shadow_only_option_count": len(shadow_enriched),
                              "excluded_option_reasons": dict(shadow_excluded)},
            "formal_model_outputs": formal_predictions,
            "shadow_only_model_outputs": shadow_predictions,
            "shadow_window_model_outputs": all_window_predictions,
            "shadow_only_model_output_snapshot_event_count": len({
                event_key(leg) for leg in shadow_prediction_legs if event_key(leg)
            }),
            "shadow_only_model_output_snapshot_option_count": len(shadow_prediction_legs),
            "shadow_only_international_market_event_count": len(shadow_international_events),
            "shadow_only_sharp_market_event_count": len(shadow_sharp_events),
            "shadow_only_model_and_sharp_event_count": len(shadow_prediction_events & shadow_sharp_events),
            "shadow_window_international_market_event_count": len(all_window_international_events),
            "shadow_window_sharp_market_event_count": len(all_window_sharp_events),
            "shadow_window_model_and_sharp_event_count": len(shadow_window_prediction_events & all_window_sharp_events),
        }
        return {"selected_leg_count": len(enriched), "snapshot_count": len(snapshots) + len(shadow_snapshots),
                "formal_snapshot_count": len(snapshots), "shadow_snapshot_count": len(shadow_snapshots),
                "model_candidate_probability_count": sum(row.get("model_candidate_probability_fused") is not None for row in snapshots),
                "excluded_reason_counts": dict(excluded),
                "model_probability_count": sum(row.get("model_probability") is not None for row in snapshots),
                "market_baseline_only_count": sum(row.get("model_probability") is None for row in snapshots),
                "shadow_coverage": shadow_coverage}

    def _stage_observations(self, window_id: str, stage_data: Path) -> dict[str, Any]:
        legs = [_leg_from_payload(row) for row in _read_json(stage_data / "selected_legs.json", [])]
        count = self.odds_watcher.record_batch_from_legs(legs, now=self.clock())
        return {"observation_count": count, "history_path": str(self.odds_watcher.history_path),
                "run_window_id": window_id}

    def _stage_parlays(self, window_id: str, run_id: str, stage_data: Path) -> dict[str, Any]:
        legs = [_leg_from_payload(row) for row in _read_json(stage_data / "selected_legs.json", [])]
        tiers = {}
        search_diagnostics = {}
        tier_defs = self.config.get("parlay_tiers", [
            {"name": "10-25x", "min": 10, "max": 25},
            {"name": "25-75x", "min": 25, "max": 75},
            {"name": "75-200x", "min": 75, "max": 200},
            {"name": "200-500x", "min": 200, "max": 500},
        ])
        total_budget = max(len(tier_defs), int(self.config.get("parlay_total_node_budget", 1000000)))
        batch_budget = max(1, int(self.config.get("parlay_batch_node_budget", 25000)))
        scope = self._current_utc().isoformat()
        deadline = time.monotonic() + max(1, float(self.config.get("parlay_total_seconds", 120)))
        progress_path = stage_data / "parlay_search_progress.json"
        saved = _read_json(progress_path, {})
        pool_hash = hashlib.sha256(json.dumps({"legs":[_leg_payload(leg) for leg in legs],
            "tiers":tier_defs,"experiment_id":get_current_experiment_identity()["experiment_id"]},
            sort_keys=True,default=_json_default).encode('utf-8')).hexdigest()
        saved_scope = parse_aware_time(saved.get("scope_as_of"))
        reusable = (saved.get("pool_hash") == pool_hash and saved_scope is not None
                    and saved_scope <= parse_aware_time(scope)
                    and all(assess_leg(leg, now=self._current_utc())["is_ready"] for leg in legs))
        states = saved.get("states", {}) if reusable else {}
        if reusable:
            scope = saved["scope_as_of"]
        remaining = total_budget
        pending = list(tier_defs)
        while pending and remaining > 0 and time.monotonic() < deadline:
            next_pending = []
            for tier in pending:
                if remaining <= 0 or time.monotonic() >= deadline:
                    next_pending.append(tier)
                    continue
                name = tier["name"]
                diag = {}
                result = self.parlay_engine.search_parlays(
                    legs=legs, min_odds=float(tier["min"]), max_odds=float(tier["max"]),
                    signal_filter="wild", min_legs=2, max_legs=6,
                    diagnostics=diag, search_budget=min(batch_budget, remaining),
                    resume_state=states.get(name), scope_as_of=scope,
                    deadline_monotonic=deadline,
                )
                remaining -= diag["visited_nodes_this_call"]
                states[name] = result.search_state
                diag.pop("resume_state", None)
                search_diagnostics[name] = diag
                tiers[name] = result
                if not diag["search_complete"]:
                    next_pending.append(tier)
            pending = next_pending
            _write_json_atomic(progress_path, {"scope_as_of":scope,"states":states,"pool_hash":pool_hash,
                "total_node_budget":total_budget,"total_seconds":self.config.get("parlay_total_seconds",120),
                "remaining_node_budget":remaining,"resume_policy":"same exact fresh quote/evidence pool only"})
        for tier in tier_defs:
            if tier["name"] not in search_diagnostics:
                search_diagnostics[tier["name"]] = {"search_complete":False,"search_status":"NOT_STARTED_TOTAL_LIMIT",
                                                    "global_top_guarantee":False,"visited_nodes":0}
                tiers[tier["name"]] = {"high_consensus":[],"aggressive":[],"moonshot":[]}
        _write_json_atomic(stage_data / "parlay_search_diagnostics.json", search_diagnostics)
        records = self.parlay_logger.log_daily_parlays(
            tiers, prediction_snapshots=self.snapshot_logger.get_all_snapshots(),
            run_window_id=window_id, run_id=run_id,
        )
        _write_json_atomic(stage_data / "parlay_entry_ids.json", [row.get("snapshot_id") for row in records])
        return {"tier_record_count": len(records), "search_diagnostics": search_diagnostics,
                "candidate_count": sum(int(row.get("total_candidate_count", 0)) for row in records),
                "linked_snapshot_count": len(_read_json(stage_data / "snapshot_ids.json", []))}

    def _stage_settlement(self, stage_data: Path) -> dict[str, Any]:
        from scripts.settle_results import settle_snapshot_results
        from core.persistence import iter_jsonl
        snapshots = iter_jsonl(self.snapshot_logger.log_path)
        result = settle_snapshot_results(self._result_engine, snapshots, now=self.clock())
        _write_json_atomic(stage_data / "settlement_audit.json", result)
        parlay_result = self._result_engine.settle_parlays_against_snapshots()
        if any(row.get("fetch_status") == "FETCH_ERROR" for row in result.get("coverage", {}).values()):
            raise RuntimeError("至少一個賽果來源抓取失敗；結算摘要已保存，需重試。")
        return {"settled_snapshots": result.get("settled", 0), "unresolved_snapshots": result.get("unresolved", 0),
                "deferred_snapshots": result.get("deferred_snapshots", 0),
                "deferred_observations": result.get("deferred_observations", []),
                "result_games": result.get("games", 0), "coverage": result.get("coverage", {}),
                "unmatched_observations_sampled": result.get("unmatched_observations_sampled", 0),
                "settled_parlay_candidates": parlay_result.get("settled_candidates", 0)}





    def _stage_soccer_model_update(self, stage_data: Path) -> dict[str, Any]:
        """Refresh isolated Football-Data.co.uk Dixon-Coles training files.

        Each league file is replaced only after every requested season has a
        valid response and the parsed dataset passes basic integrity checks.
        Scores are retained only for dated, completed matches before today's
        UTC date; the model adapter applies the stricter prediction cutoff.
        """
        settings = (self.config.get("soccer_model_update", {}) or {})
        if not settings.get("enabled", True):
            result = {"status": "SKIPPED", "reason": "soccer_model_update.enabled is false"}
            _write_json_atomic(stage_data / "soccer_model_update.json", result)
            return result
        leagues = settings.get("leagues", {"eng.1": "E0", "esp.1": "SP1"})
        seasons = [str(value) for value in settings.get("seasons", ["2324", "2425", "2526", "2627"])]
        if not isinstance(leagues, dict) or not leagues or not seasons:
            return {"status": "UNAVAILABLE", "reason": "no supported Football-Data leagues or seasons configured"}
        model_cache = self.data_root / "cache" / "models" / "penaltyblog_dixon_coles"
        model_cache.mkdir(parents=True, exist_ok=True)
        state_path = self.data_root / "model_state" / "soccer_data_refresh.json"
        refresh_state = _read_json(state_path, {})
        now = self._current_utc()
        refresh_hours = max(1, int(settings.get("refresh_interval_hours", 6)))
        last_ok = parse_aware_time(refresh_state.get("last_success_utc")) if isinstance(refresh_state, dict) else None
        if last_ok and now - last_ok < timedelta(hours=refresh_hours):
            result = {"status": "FRESH_CACHE", "last_success_utc": last_ok.isoformat(),
                      "leagues": refresh_state.get("leagues", {})}
            _write_json_atomic(stage_data / "soccer_model_update.json", result)
            return result

        fetcher = self._soccer_data_fetcher or self._fetch_football_data_csv
        max_attempts = max(1, int(settings.get("max_attempts", 3)))
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for league, source_code in leagues.items():
            league = str(league)
            old_path = model_cache / f"real_matches_{league}.json"
            match_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
            sources: list[dict[str, Any]] = []
            raw_hashes: list[str] = []
            try:
                for season in seasons:
                    url = f"https://www.football-data.co.uk/mmz4281/{season}/{source_code}.csv"
                    body = None
                    last_error = None
                    for attempt in range(max_attempts):
                        try:
                            body, fetched_at = fetcher(url)
                            if not isinstance(body, bytes) or not body:
                                raise ValueError("empty or non-byte CSV response")
                            break
                        except Exception as exc:
                            last_error = exc
                            if attempt + 1 < max_attempts:
                                import time
                                time.sleep(min(2 ** attempt, 4))
                    if body is None:
                        raise RuntimeError(f"{url}: {type(last_error).__name__}: {last_error}")
                    digest = hashlib.sha256(body).hexdigest()
                    raw_hashes.append(digest)
                    sources.append({"season": season, "url": url, "fetched_at_utc": fetched_at,
                                    "sha256": digest, "byte_count": len(body)})
                    try:
                        text = body.decode("utf-8-sig", errors="strict")
                    except UnicodeDecodeError:
                        text = body.decode("cp1252", errors="strict")
                    rows = csv.DictReader(StringIO(text))
                    required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
                    if not required.issubset(set(rows.fieldnames or [])):
                        raise ValueError(f"{url} missing required columns {sorted(required - set(rows.fieldnames or []))}")
                    valid_for_season = 0
                    for raw in rows:
                        try:
                            match_date = _parse_football_data_date(raw.get("Date"))
                            if match_date is None:
                                continue
                            home_goals, away_goals = int(raw["FTHG"]), int(raw["FTAG"])
                            home, away = str(raw["HomeTeam"] or "").strip(), str(raw["AwayTeam"] or "").strip()
                        except (TypeError, ValueError, KeyError):
                            continue
                        if (match_date >= now.date() or home_goals < 0 or away_goals < 0
                                or not home or not away or home.casefold() == away.casefold()):
                            continue
                        valid_for_season += 1
                        row = {"date": match_date.isoformat(), "home_team": home, "away_team": away,
                               "home_goals": home_goals, "away_goals": away_goals}
                        key = (row["date"], home.casefold(), away.casefold(), league)
                        previous = match_by_key.get(key)
                        if previous and (previous["home_goals"], previous["away_goals"]) != (home_goals, away_goals):
                            raise ValueError(f"conflicting duplicate official score for {key[:3]}")
                        match_by_key[key] = row
                    if valid_for_season == 0:
                        raise ValueError(f"{url} has no valid completed match rows; preserving prior cache")
                matches = sorted(match_by_key.values(), key=lambda row: (row["date"], row["home_team"], row["away_team"]))
                if len(matches) < int(settings.get("minimum_matches_per_league", 60)):
                    raise ValueError(f"only {len(matches)} completed dated matches; refusing to replace cached training data")
                file_content = {
                    "dataset_source": "Football-Data.co.uk official CSV downloads",
                    "dataset_url": "https://www.football-data.co.uk/",
                    "dataset_version": now.date().isoformat(),
                    "downloaded_at": now.isoformat(),
                    "dataset_seasons": seasons,
                    "source_files": sources,
                    "raw_source_sha256": raw_hashes,
                    "matches": matches,
                    "point_in_time_policy": "dated completed matches only; prediction adapter enforces match_date < prediction_date",
                }
                _write_json_atomic(old_path, file_content)
                results[league] = {"status": "UPDATED", "match_count": len(matches),
                                   "latest_match_date": matches[-1]["date"], "source_files": sources,
                                   "cache_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest()}
            except Exception as exc:
                # Any failure leaves the last valid league cache byte-for-byte intact.
                errors[league] = f"{type(exc).__name__}: {exc}"
                results[league] = {"status": "FETCH_FAILED_CACHE_PRESERVED" if old_path.exists() else "UNAVAILABLE",
                                   "cached_file_present": old_path.exists(), "error": errors[league]}

        if results and all(value.get("status") == "UPDATED" for value in results.values()):
            _write_json_atomic(state_path, {"last_success_utc": now.isoformat(), "leagues": results})
            status = "UPDATED"
        else:
            status = "PARTIAL_OR_FAILED"
        result = {"status": status, "source": "Football-Data.co.uk", "leagues": results,
                  "errors": errors, "refresh_due_at_utc": (now + timedelta(hours=refresh_hours)).isoformat()}
        _write_json_atomic(stage_data / "soccer_model_update.json", result)
        return result

    @staticmethod
    def _fetch_football_data_csv(url: str) -> tuple[bytes, str]:
        from urllib.request import Request, urlopen
        request = Request(url, headers={"Accept": "text/csv", "User-Agent": "sportslottery-research/1.0"})
        with urlopen(request, timeout=30) as response:
            body = response.read()
        return body, datetime.now(timezone.utc).isoformat()

