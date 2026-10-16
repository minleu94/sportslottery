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

from core.bet_validation import assess_leg, parse_aware_time
from core.experiment_identity import get_current_experiment_identity
from core.odds_watcher import OddsWatcher
from core.parlay_engine import ParlayEngine
from core.research_reporting import ResearchReportMixin
from core.research_mlb import MLBResearchMixin, _mlb_game_is_cancelled
from core.shadow_parlay_logger import ShadowParlayLogger
from core.signal_hub import SignalHub
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import get_strategy_metadata
from integrations.common.models import PredictionSignal, TaiwanLeg
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


def _json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, default=_json_default)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers can briefly hold a destination open. Retry only the
        # atomic replace operation; never truncate the old state or rewrite the
        # temporary payload between attempts.
        retry_delays = (0.05, 0.1, 0.15, 0.2)
        for attempt in range(len(retry_delays) + 1):
            try:
                os.replace(temp_name, path)
                break
            except PermissionError:
                if attempt >= len(retry_delays):
                    raise
                time.sleep(retry_delays[attempt])
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _mlb_game_date(game: dict[str, Any]) -> date | None:
    stamp = parse_aware_time(game.get("gameDate"))
    return stamp.date() if stamp else None


def _mlb_game_is_final(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    detailed = str(status.get("detailedState") or "").casefold()
    coded = str(status.get("codedGameState") or "").upper()
    # Stats API can report abstractGameState=Final while the coded/detailed
    # state is still a postponement stub. That is not a completed result.
    if coded == "D" or "postpon" in detailed:
        return False
    if not (status.get("abstractGameState") == "Final" or status.get("codedGameState") == "F"):
        return False
    # A final label alone is not usable Elo evidence. Preserve/requery incomplete
    # finals as pending; do not invent scores or advance the rating watermark.
    from integrations.results.models import parse_score
    teams = game.get("teams") or {}
    linescore = (game.get("linescore") or {}).get("teams") or {}
    return all(parse_score((linescore.get(side) or {}).get("runs", (teams.get(side) or {}).get("score"))) is not None
               for side in ("home", "away"))


def _mlb_game_is_regular_or_postseason(game: dict[str, Any]) -> bool:
    # Stats API gameType: R regular season; F/D/L/W postseason rounds.
    # Spring training (S), exhibitions (E), all-star (A), and unknown types
    # are retained in the source ledger but excluded from this model protocol.
    game_type = str(game.get("gameType") or "").strip().upper()
    return game_type in {"R", "F", "D", "L", "W"}


def _mlb_reschedule_target_date(game: dict[str, Any]) -> date | None:
    """Read only an explicit MLB date field; never derive a new game date."""
    # Official calendar dates can differ from the UTC date of a night game.
    for key in ("rescheduleGameDate", "rescheduleDate", "officialDate"):
        value = game.get(key)
        if not value:
            continue
        parsed = parse_aware_time(value)
        if parsed:
            return parsed.date()
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
    return None


def _mlb_needs_live_reconciliation(game: dict[str, Any], completed_through: date) -> bool:
    if not _mlb_game_is_regular_or_postseason(game) or _mlb_game_is_final(game) or _mlb_game_is_cancelled(game):
        return False
    scheduled = _mlb_game_date(game)
    target = _mlb_reschedule_target_date(game)
    return bool(scheduled and target and scheduled <= completed_through and target <= completed_through)


def _mlb_normalize_live_feed(
    payload: dict[str, Any], schedule_game: dict[str, Any], *, observed_at_utc: str,
) -> dict[str, Any]:
    """Normalize a verified MLB live feed to the Stats schedule-game shape.

    Reconciliation requires the same gamePk, same home/away team IDs, an
    explicit aware gameData.datetime.dateTime, a matching official reschedule
    date when supplied, and a completed final score.
    """
    game_data = payload.get("gameData") or {}
    live = payload.get("liveData") or {}
    game_meta = game_data.get("game") or {}
    game_pk = str(game_meta.get("pk") or payload.get("gamePk") or "")
    expected_pk = str(schedule_game.get("gamePk") or "")
    if not game_pk or game_pk != expected_pk:
        raise ValueError(f"live feed gamePk mismatch: expected {expected_pk}, received {game_pk or 'missing'}")

    schedule_teams = schedule_game.get("teams") or {}
    live_teams = game_data.get("teams") or {}
    normalized_teams = {}
    for side in ("home", "away"):
        schedule_team = (schedule_teams.get(side) or {}).get("team") or {}
        live_team = live_teams.get(side) or {}
        schedule_id, live_id = str(schedule_team.get("id") or ""), str(live_team.get("id") or "")
        if not schedule_id or schedule_id != live_id:
            raise ValueError(f"live feed {side} team ID mismatch for gamePk={expected_pk}: {schedule_id or 'missing'} != {live_id or 'missing'}")

    game_datetime = game_data.get("datetime") or {}
    start_time = str(game_datetime.get("dateTime") or "")
    start_aware = parse_aware_time(start_time)
    if not start_aware:
        raise ValueError(f"live feed gamePk={expected_pk} has no aware gameData.datetime.dateTime")
    official_date = str(game_datetime.get("officialDate") or "")
    target_date = _mlb_reschedule_target_date(schedule_game)
    if target_date:
        if not official_date:
            raise ValueError(f"live feed gamePk={expected_pk} has no officialDate for reschedule validation")
        try:
            live_official_date = date.fromisoformat(official_date[:10])
        except ValueError as exc:
            raise ValueError(f"live feed gamePk={expected_pk} has invalid officialDate {official_date!r}") from exc
        if live_official_date != target_date:
            raise ValueError(f"live feed officialDate {official_date} does not match schedule reschedule date {target_date}")

    schedule_game_type = str(schedule_game.get("gameType") or "").strip().upper()
    live_game_type = str(game_meta.get("type") or "").strip().upper()
    if schedule_game_type and live_game_type and schedule_game_type != live_game_type:
        raise ValueError(f"live feed gameType {live_game_type} does not match schedule gameType {schedule_game_type}")

    status = game_data.get("status") or {}
    detailed_state = str(status.get("detailedState") or "").casefold()
    coded_state = str(status.get("codedGameState") or "").upper()
    if coded_state == "D" or "postpon" in detailed_state:
        raise ValueError(f"live feed gamePk={expected_pk} still reports a postponement")
    if status.get("abstractGameState") != "Final" and coded_state != "F":
        raise ValueError(f"live feed gamePk={expected_pk} is not final")
    linescore = live.get("linescore") or {}
    line_teams = linescore.get("teams") or {}
    scores = {}
    for side in ("home", "away"):
        value = (line_teams.get(side) or {}).get("runs")
        from integrations.results.models import parse_score
        parsed = parse_score(value)
        if parsed is None:
            raise ValueError(f"live feed gamePk={expected_pk} missing final {side} runs")
        scores[side] = parsed
        source_team = live_teams[side]
        normalized_teams[side] = {
            "team": {"id": int(str(source_team["id"])), "name": str(source_team.get("name") or "")},
            "score": parsed,
        }

    return {
        "gamePk": int(game_pk),
        "gameType": str(game_meta.get("type") or schedule_game.get("gameType") or ""),
        "gameDate": start_time,
        "officialDate": official_date or start_aware.date().isoformat(),
        "status": dict(status),
        "teams": normalized_teams,
        "linescore": {"teams": {side: {"runs": score} for side, score in scores.items()}},
        "_reconciled_from_live_feed": True,
        "_live_feed_observed_at_utc": observed_at_utc,
        "_source_observation": {
            "provider": "MLB_STATS_API_LIVE_FEED",
            "official_game_pk": game_pk,
            "official_start_time_utc": start_time,
            "home_team_id": str(normalized_teams["home"]["team"]["id"]),
            "away_team_id": str(normalized_teams["away"]["team"]["id"]),
        },
    }


def _parse_football_data_date(value: Any) -> date | None:
    """Football-Data date columns use both two- and four-digit years."""
    text = str(value or "").strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _leg_payload(leg: TaiwanLeg) -> dict[str, Any]:
    return leg.to_dict()


def _leg_from_payload(row: dict[str, Any]) -> TaiwanLeg:
    known = {item.name for item in fields(TaiwanLeg)}
    payload = {key: value for key, value in row.items() if key in known}
    signal_fields = {item.name for item in fields(PredictionSignal)}
    payload["signals"] = [
        signal if isinstance(signal, PredictionSignal) else
        PredictionSignal(**{key: value for key, value in signal.items() if key in signal_fields})
        for signal in payload.get("signals", []) if isinstance(signal, (dict, PredictionSignal))
    ]
    return TaiwanLeg(**payload)


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

    def _window_legs(self, window_id: str, now: datetime, stage_data: Path):
        lead = max(1, int(self.config.get("pregame_lead_minutes", 60)))
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

    def _stage_snapshots(self, window_id: str, now: datetime, stage_data: Path) -> dict[str, Any]:
        # A resumed stage can run long after the source stage completed. Use the
        # wall clock at eligibility time so old cached quotes cannot be sealed.
        now = self._current_utc()
        selected, excluded = self._window_legs(window_id, now, stage_data)
        enriched = [self._signal_hub.evaluate_taiwan_leg(leg) for leg in selected]
        for leg in enriched:
            leg.signal_evidence["observation_window_id"] = window_id
        snapshots = self.snapshot_logger.log_batch(enriched, observation_window_id=window_id)
        for leg, snapshot in zip(enriched, snapshots):
            leg.signal_evidence["snapshot_id"] = snapshot.get("snapshot_id")
            leg.signal_evidence["forward_validation_eligible"] = snapshot.get("forward_validation_eligible")
        _write_json_atomic(stage_data / "selected_legs.json", [_leg_payload(leg) for leg in enriched])
        _write_json_atomic(stage_data / "snapshot_ids.json", [row.get("snapshot_id") for row in snapshots])
        return {"selected_leg_count": len(enriched), "snapshot_count": len(snapshots),
                "model_candidate_probability_count": sum(row.get("model_candidate_probability_fused") is not None for row in snapshots),
                "excluded_reason_counts": dict(excluded),
                "model_probability_count": sum(row.get("model_probability") is not None for row in snapshots),
                "market_baseline_only_count": sum(row.get("model_probability") is None for row in snapshots)}

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
        snapshots = self.snapshot_logger.get_all_snapshots()
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

