from datetime import date, datetime, timedelta, timezone
import json
import csv
from pathlib import Path
from io import StringIO
import pytest

from core.odds_watcher import OddsWatcher
from core.research_pipeline import ResearchPipeline, _parse_football_data_date, _write_json_atomic
from core.experiment_identity import get_current_experiment_identity
from core.signal_hub import SignalHub
from core.settlement_engine import SettlementEngine
from core.shadow_parlay_logger import ShadowParlayLogger
from core.snapshot_logger import PredictionSnapshotLogger
from integrations.common.models import PredictionSignal, TaiwanLeg


class FixtureOddsAdapter:
    def __init__(self, legs):
        self.legs = legs

    def get_taiwan_legs(self, alliances, force_refresh=False):
        return self.legs

    def get_source_status(self):
        if not self.legs:
            return {}
        return {"1": {"source_status": "LIVE", "observed_at": self.legs[0].odds_scraped_at}}


class FixtureSignalHub:
    def evaluate_taiwan_leg(self, leg):
        leg.signal_evidence["probability_status"] = "MARKET_BASELINE_ONLY"
        return leg


class FixtureModelRegistry:
    def evaluate_leg_across_models(self, leg):
        event_start = datetime.fromisoformat(leg.start_time_utc)
        return [PredictionSignal(
            source_id="fixture-elo", source_name="Fixture Elo", source_type="MODEL",
            source_category="OPEN_SOURCE_ENGINE", independence_group="FIVETHIRTYEIGHT_ELO",
            event_id=leg.event_id, market=leg.market, selection=leg.selection,
            probability=0.62, score=8.0, confidence="MED", freshness_status="FRESH",
            data_as_of=(event_start - timedelta(days=2)).isoformat(),
            metadata={"model_id": "fixture-elo", "model_version": "fixture-v1", "initialized": True,
                      "model_candidate_probability": 0.62, "prediction_source_scope": "FIXTURE",
                      "model_acceptance": {"accepted": False, "status": "INSUFFICIENT_SAMPLE"}},
        )]


class EmptyFixtureAdapter:
    def get_expert_signal(self, leg):
        return None

    def get_crowd_signal(self, leg):
        return None


class FrozenDateTime(datetime):
    current = None

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def _offline_soccer_update(pipeline):
    pipeline._stage_soccer_model_update = lambda stage: {"status": "OFFLINE_TEST_STUB"}
    return pipeline


def test_report_counts_failed_attempts_and_excludes_unknown_future_outcomes(tmp_path):
    from types import SimpleNamespace
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    root = tmp_path / "research"
    pipeline = ResearchPipeline(data_root=root, clock=lambda: now)
    # These count-only fixtures never enter a valid prediction cohort; they
    # exercise the report's own time cutoff independently of payload checks.
    pipeline.snapshot_logger = SimpleNamespace(get_all_snapshots=lambda: [{
        "timestamp":now.isoformat(), "is_settled":True, "settlement_status":"WON",
        "settled_at":(now + timedelta(days=1)).isoformat(),
    }])
    pipeline.parlay_logger = ShadowParlayLogger(root / "historical/parlay_snapshots.jsonl")
    health = root / "source_health/playsport.jsonl"
    health.parent.mkdir(parents=True)
    observations = [
        {"source_status":"FETCH_ERROR", "observed_at":None,"recorded_at":now.isoformat()},
        {"source_status":"LIVE", "observed_at":now.isoformat()},
        {"source_status":"FETCH_ERROR", "recorded_at":(now + timedelta(days=1)).isoformat()},
    ]
    health.write_text("\n".join(json.dumps(row) for row in observations), encoding="utf-8")
    stage = root / "runs/replay/data"
    stage.mkdir(parents=True)
    pipeline._stage_report(stage)
    report = json.loads((root / "reports/weekly_2026-10-01.json").read_text(encoding="utf-8"))
    assert report["source_health_observation_counts"] == {"FETCH_ERROR":1,"LIVE":1}
    assert report["single_leg"]["recorded_snapshots"] == 1
    assert report["single_leg"]["settled_count"] == 0
    assert report["single_leg"]["valid_current_experiment_unique_observations"][
        "report_outcomes_unknown_at_cutoff_excluded"] == 1
def _leg(now):
    return TaiwanLeg(
        event_id="mlb-evt-1", canonical_event_id="MLB:away-home:fixture", sport="baseball", league="MLB",
        market="不讓分", selection="Away 不讓分勝", side="客", taiwan_odds=2.1,
        start_time="2026-10-13 19:00", start_time_utc=(now + timedelta(minutes=30)).isoformat(),
        away_team="Away Team", home_team="Home Team", odds_scraped_at=now.isoformat(),
        odds_status="FRESH", signal_evidence={"market_complete": True, "source_game_id": "result-1",
                                               "market_outcome_odds": {"主": 1.95, "客": 2.1}},
    )


def test_pipeline_dry_run_has_no_filesystem_or_network_side_effects(tmp_path):
    now = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
    root = tmp_path / "research"
    pipeline = ResearchPipeline(data_root=root, clock=lambda: now)
    result = pipeline.run(dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert result["plan"]["network_enabled"] is False
    assert result["plan"]["mutations_enabled"] is False
    assert not root.exists()


def test_pipeline_runs_isolated_snapshot_settlement_report_end_to_end(tmp_path, monkeypatch):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    FrozenDateTime.current = now
    monkeypatch.setattr("core.snapshot_logger.datetime", FrozenDateTime)
    leg = _leg(now)
    data_root = tmp_path / "research"
    result_game = {
        # Offline API double returns the normalized shape and provenance label
        # used by the official MLB Stats API adapter; no live result is fetched.
        "provider": "MLB Stats API (statsapi.mlb.com)", "provider_event_id": "result-1", "sport": "baseball", "league": "MLB",
        "away_team": "Away Team", "home_team": "Home Team", "start_time_utc": leg.start_time_utc,
        "status": "FINAL", "away_score": 2, "home_score": 1, "final_score": "2:1",
    }
    engine = SettlementEngine(
        snapshot_logger=PredictionSnapshotLogger(data_root / "historical" / "prediction_snapshots.jsonl"),
        parlay_logger=ShadowParlayLogger(data_root / "historical" / "parlay_snapshots.jsonl"),
        odds_watcher=OddsWatcher(data_root / "historical" / "odds_history.jsonl"),
    )
    result_date = datetime.fromisoformat(leg.start_time_utc).date().isoformat()
    engine.fetch_results = lambda sport, league, date_str, source_ids=None: [result_game] if date_str == result_date else []
    hub = SignalHub(expert_adapter=EmptyFixtureAdapter(), crowd_adapter=EmptyFixtureAdapter(),
                    model_registry=FixtureModelRegistry())
    pipeline = ResearchPipeline(
        data_root=data_root, odds_adapter=FixtureOddsAdapter([leg]), signal_hub=hub,
        result_engine=engine, clock=lambda: now,
        model_updater=lambda **kwargs: {"updated_games": 0, "data_as_of": None},
    )
    _offline_soccer_update(pipeline)

    # The scheduled command always passes --resume; with no old run this must
    # start a fresh window instead of failing installation's first tick.
    result = pipeline.run(resume=True)
    assert result["status"] == "COMPLETE", result
    state_path = data_root / "runs" / result["run_window_id"] / "run.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "COMPLETE"
    assert state["stages"]["pregame_snapshots"]["result"]["snapshot_count"] == 1
    assert state["stages"]["odds_observations"]["result"]["observation_count"] == 1
    assert state["stages"]["multi_sport_settlement"]["result"]["settled_snapshots"] == 0
    assert state["stages"]["multi_sport_settlement"]["result"]["deferred_snapshots"] == 1
    sealed = pipeline.snapshot_logger.get_all_snapshots()[0]
    assert sealed["model_candidate_probability_raw"] == 0.62
    assert sealed["model_candidate_probability_fused"] is not None
    assert sealed["probability_status"] == "MARKET_BASELINE_ONLY"
    assert sealed["model_probability"] is None  # A rejected model cannot become the production point estimate.
    assert sealed["model_candidate_provenances"][0]["acceptance_status"] == "INSUFFICIENT_SAMPLE"

    # A later cadence settles the prior prediction only after event start; the
    # source adapter now has no upcoming selections to add.
    later = now + timedelta(hours=3)
    FrozenDateTime.current = later
    empty_engine = SettlementEngine(
        snapshot_logger=PredictionSnapshotLogger(data_root / "historical" / "prediction_snapshots.jsonl"),
        parlay_logger=ShadowParlayLogger(data_root / "historical" / "parlay_snapshots.jsonl"),
        odds_watcher=OddsWatcher(data_root / "historical" / "odds_history.jsonl"),
    )
    empty_engine.fetch_results = lambda sport, league, date_str, source_ids=None: [result_game] if date_str == result_date else []
    later_pipeline = ResearchPipeline(
        data_root=data_root, odds_adapter=FixtureOddsAdapter([]), signal_hub=hub,
        result_engine=empty_engine, clock=lambda: later,
        model_updater=lambda **kwargs: {"updated_games": 0, "data_as_of": None},
    )
    _offline_soccer_update(later_pipeline)
    later_result = later_pipeline.run(resume=True)
    assert later_result["status"] == "COMPLETE", later_result
    later_state = json.loads((data_root / "runs" / later_result["run_window_id"] / "run.json").read_text(encoding="utf-8"))
    assert later_state["stages"]["multi_sport_settlement"]["result"]["settled_snapshots"] == 1
    settled = later_pipeline.snapshot_logger.get_all_snapshots()[0]
    assert datetime.fromisoformat(settled["settled_at"]) >= datetime.fromisoformat(settled["event_start"])
    report_path = data_root / "reports" / f"weekly_{now:%Y-%m-%d}.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["wallet_data_used"] is False
    assert report["single_leg"]["settled_count"] == 1
    assert report["single_leg"]["market_baseline"]["n"] == 0
    assert report["single_leg"]["model"]["sample_size"] == 0
    assert report["single_leg"]["research_candidate"]["paired_probability_cohort_n"] == 1
    assert report["single_leg"]["research_candidate"]["model_candidate"]["n"] == 1
    assert report["whole_ticket"]["operational_reference_only"] is True
    assert not (data_root / "wallet").exists()

    retry = later_pipeline.run()
    assert retry["duplicate_window"] is True
    assert len(pipeline.snapshot_logger.get_all_snapshots()) == 1


def test_unknown_league_does_not_block_pipeline_report_but_supported_fetch_failure_retries(tmp_path):
    now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

    def make_pipeline(root, league, fetch):
        engine = SettlementEngine()
        engine.fetch_results = fetch
        pipeline = ResearchPipeline(
            data_root=root, odds_adapter=FixtureOddsAdapter([]), signal_hub=FixtureSignalHub(),
            result_engine=engine, clock=lambda: now,
            model_updater=lambda **kwargs: {"updated_games": 0, "data_as_of": None},
        )
        _offline_soccer_update(pipeline)
        pipeline._components()
        pipeline.snapshot_logger.log_path.parent.mkdir(parents=True, exist_ok=True)
        pipeline.snapshot_logger.log_path.write_text(json.dumps({
            "snapshot_id": f"snapshot-{league}", "timestamp": now.isoformat(),
            "snapshot_timestamp": now.isoformat(), "event_start": "2026-10-10T20:00:00Z",
            "sport": "soccer", "league": league, "away_team": "Away", "home_team": "Home",
            "market": "不讓分", "selection": "客勝", "side": "客", "taiwan_odds": 2.0,
            "is_settled": False,
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        return pipeline

    unsupported_root = tmp_path / "unsupported-research"
    unsupported = make_pipeline(
        unsupported_root, "UNKNOWN_哥倫比亞乙級聯賽",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fetch unknown league")),
    )
    result = unsupported.run(resume=True)
    assert result["status"] == "COMPLETE", result
    report = list((unsupported_root / "reports").glob("weekly_*.json"))
    assert len(report) == 1
    audit = json.loads((unsupported_root / "runs" / result["run_window_id"] / "data" / "settlement_audit.json").read_text(encoding="utf-8"))
    coverage = audit["coverage"]["soccer/UNKNOWN_哥倫比亞乙級聯賽"]
    assert coverage["status"] == "UNSUPPORTED"
    assert coverage["fetch_status"] == "NOT_ATTEMPTED"
    assert audit["unmatched_observations"][0]["reason"] == "RESULT_SOURCE_UNSUPPORTED"

    supported_root = tmp_path / "supported-research"
    supported = make_pipeline(
        supported_root, "PREMIER",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("temporary provider HTTP failure")),
    )
    failed = supported.run(resume=True)
    assert failed["status"] == "FAILED"
    failed_audit = json.loads((supported_root / "runs" / failed["run_window_id"] / "data" / "settlement_audit.json").read_text(encoding="utf-8"))
    assert failed_audit["coverage"]["soccer/PREMIER"]["fetch_status"] == "FETCH_ERROR"


def test_pipeline_rejects_production_data_root(tmp_path):
    try:
        ResearchPipeline(data_root="data", clock=lambda: datetime.now(timezone.utc))
    except ValueError as exc:
        assert "production data" in str(exc)
    else:
        raise AssertionError("production data root should be rejected")


def test_parlay_window_retry_is_idempotent_and_preserves_run_lineage(tmp_path):
    logger = ShadowParlayLogger(tmp_path / "parlays.jsonl")
    window_id = "20261013T1800Z"
    first = logger.log_daily_parlays({}, prediction_snapshots=[], run_window_id=window_id, run_id="run-1")
    second = logger.log_daily_parlays({}, prediction_snapshots=[], run_window_id=window_id, run_id="run-1-retry")

    assert len(first) == 4  # One record per configured multiplier tier.
    assert [row["snapshot_id"] for row in second] == [row["snapshot_id"] for row in first]
    assert all(row["run_window_id"] == window_id for row in first)
    assert all(row["run_id"] == "run-1" for row in first)
    assert all(row["experiment_identity"] == get_current_experiment_identity() for row in first)
    assert len(logger.get_all_parlay_snapshots()) == 4


def test_elo_warmup_uses_explicit_prior_without_fabricating_result_watermark(tmp_path):
    now = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
    captured = {}

    def updater(**kwargs):
        captured.update(kwargs)
        return {"updated_games": 0, "data_as_of": None, "source": "MLB Stats API"}

    root = tmp_path / "research"
    pipeline = ResearchPipeline(data_root=root, clock=lambda: now, model_updater=updater)
    stage_data = root / "runs" / "fixture" / "data"
    stage_data.mkdir(parents=True)
    result = pipeline._stage_model_update(stage_data)

    state = json.loads((root / "model_state" / "live_mlb_elo.json").read_text(encoding="utf-8"))
    coverage = json.loads((root / "model_state" / "live_mlb_elo_fetch_coverage.json").read_text(encoding="utf-8"))
    assert result["status"] == "WARMUP_IN_PROGRESS"
    assert result["initialization_mode"] == "neutral_1500_official_warmup"
    assert captured["start_date"].isoformat() == "2025-03-01"
    assert captured["end_date"].isoformat() == "2025-03-07"
    assert state["source"].startswith("Neutral 1500 initialization")
    assert state["data_as_of"] is None  # Schedule-query coverage is not a result watermark.
    assert coverage["official_schedule_queried_through"] == "2025-03-07"


def test_resume_skips_exhausted_run_and_starts_current_window(tmp_path):
    now = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
    root = tmp_path / "research"
    exhausted_id = "20261013T1745Z"
    old_state_path = root / "runs" / exhausted_id / "run.json"
    old_state_path.parent.mkdir(parents=True)
    old_state_path.write_text(json.dumps({
        "run_id": "exhausted", "run_window_id": exhausted_id, "started_at": (now - timedelta(minutes=5)).isoformat(),
        "status": "FAILED", "stages": {"source_fetch_health": {"status": "FAILED", "attempts": 3}},
    }), encoding="utf-8")
    pipeline = ResearchPipeline(
        data_root=root, odds_adapter=FixtureOddsAdapter([]), signal_hub=FixtureSignalHub(),
        clock=lambda: now, model_updater=lambda **kwargs: {"updated_games": 0},
    )
    _offline_soccer_update(pipeline)

    result = pipeline.run(resume=True)

    assert result["status"] == "COMPLETE", result
    assert result["run_window_id"] != exhausted_id
    assert json.loads(old_state_path.read_text(encoding="utf-8"))["run_id"] == "exhausted"


def test_resumed_snapshot_stage_rechecks_quote_age_at_current_clock(tmp_path):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    old = _leg(now)
    old.odds_scraped_at = (now - timedelta(minutes=20)).isoformat()
    old.odds_age_minutes = 20
    root = tmp_path / "research"
    stage_data = root / "runs" / "old-window" / "data"
    stage_data.mkdir(parents=True)
    (stage_data / "source_legs.json").write_text(json.dumps([old.to_dict()]), encoding="utf-8")
    pipeline = ResearchPipeline(
        data_root=root, odds_adapter=FixtureOddsAdapter([]), signal_hub=FixtureSignalHub(),
        clock=lambda: now,
    )
    pipeline._components()

    result = pipeline._stage_snapshots("old-window", now - timedelta(hours=1), stage_data)

    assert result["snapshot_count"] == 0
    assert result["excluded_reason_counts"].get("ODDS_STALE") == 1


def test_atomic_json_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"previous": true}', encoding="utf-8")
    attempts = []

    def deny_replace(*args, **kwargs):
        attempts.append(args)
        raise PermissionError("simulated Windows sharing violation")

    monkeypatch.setattr("core.research_pipeline.os.replace", deny_replace)
    monkeypatch.setattr("core.research_pipeline.time.sleep", lambda _: None)
    with pytest.raises(PermissionError):
        _write_json_atomic(path, {"new": True})

    assert len(attempts) == 5
    assert len({args[0] for args in attempts}) == 1  # same flushed temp file on every retry
    assert path.read_text(encoding="utf-8") == '{"previous": true}'
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_atomic_json_replace_retries_transient_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"previous": true}', encoding="utf-8")
    original_replace = __import__("os").replace
    attempted_sources = []
    sleeps = []

    def transient_replace(source, destination):
        attempted_sources.append(source)
        if len(attempted_sources) < 3:
            raise PermissionError("simulated transient Windows sharing violation")
        original_replace(source, destination)

    monkeypatch.setattr("core.research_pipeline.os.replace", transient_replace)
    monkeypatch.setattr("core.research_pipeline.time.sleep", sleeps.append)

    _write_json_atomic(path, {"new": True})

    assert len(attempted_sources) == 3
    assert len(set(attempted_sources)) == 1
    assert sleeps == [0.05, 0.1]
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_paired_ci_only_compares_probability_scores_not_shared_returns():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = [{
        "event_start": (start + timedelta(days=index)).isoformat(),
        "model_probability": 0.6 + index * 0.01,
        "market_fair_probability": 0.52,
        "settlement_status": "WON" if index % 2 else "LOST",
        "taiwan_odds": 2.0,
    } for index in range(5)]

    result = ResearchPipeline._paired_cluster_ci(rows, replicates=10)

    assert result["status"] == "COMPLETED"
    assert result["compared_metrics"] == ["brier", "log_loss"]
    assert set(result["intervals"]) == {"brier_delta_model_minus_market", "log_loss_delta_model_minus_market"}


def test_soccer_update_persists_source_metadata_pit_data_and_preserves_good_cache(tmp_path):
    now = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
    rows = StringIO()
    writer = csv.DictWriter(rows, fieldnames=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    writer.writeheader()
    for index in range(65):
        day = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=index * 3)
        writer.writerow({"Date": day.strftime("%d/%m/%Y" if index % 2 else "%d/%m/%y"), "HomeTeam": f"Home {index}",
                         "AwayTeam": f"Away {index}", "FTHG": index % 4, "FTAG": index % 3})
    writer.writerow({"Date": "14/10/26", "HomeTeam": "Future", "AwayTeam": "Future Away", "FTHG": 1, "FTAG": 0})
    body = rows.getvalue().encode("utf-8")
    calls = []

    def fetcher(url):
        calls.append(url)
        return body, now.isoformat()

    root = tmp_path / "research"
    pipeline = ResearchPipeline(data_root=root, clock=lambda: now, soccer_data_fetcher=fetcher)
    stage = root / "runs" / "first" / "data"
    stage.mkdir(parents=True)
    result = pipeline._stage_soccer_model_update(stage)
    assert result["status"] == "UPDATED"
    assert len(calls) == 8  # 4 configured season CSVs for each supported league.
    cache = root / "cache" / "models" / "penaltyblog_dixon_coles" / "real_matches_eng.1.json"
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert len(payload["matches"]) == 65
    assert payload["matches"][-1]["date"] < "2026-10-13"
    assert payload["raw_source_sha256"]
    assert payload["source_files"][0]["url"].startswith("https://www.football-data.co.uk/")
    original_bytes = cache.read_bytes()

    failed = ResearchPipeline(data_root=root, clock=lambda: now + timedelta(hours=7),
                              soccer_data_fetcher=lambda url: (_ for _ in ()).throw(OSError("offline")))
    failed.config["soccer_model_update"]["max_attempts"] = 1
    second_stage = root / "runs" / "second" / "data"
    second_stage.mkdir(parents=True)
    outcome = failed._stage_soccer_model_update(second_stage)
    assert outcome["status"] == "PARTIAL_OR_FAILED"
    assert "FETCH_FAILED_CACHE_PRESERVED" in {row["status"] for row in outcome["leagues"].values()}
    assert cache.read_bytes() == original_bytes


def test_football_data_date_parser_reads_both_fixture_and_frozen_source_shapes():
    assert _parse_football_data_date("15/08/25").isoformat() == "2025-08-15"
    assert _parse_football_data_date("15/08/2025").isoformat() == "2025-08-15"
    frozen_path = (Path(__file__).resolve().parents[1] / "artifacts" / "validation_sources_20261012"
                   / "eng_1_2526_E0_3e3a8352f9ad.csv")
    with frozen_path.open("r", encoding="utf-8-sig", newline="") as stream:
        first = next(csv.DictReader(stream))
    assert _parse_football_data_date(first["Date"]).isoformat() == "2025-08-15"


def test_elo_official_batch_replays_multiple_same_day_games_in_order(tmp_path):
    from integrations.models.external.live_mlb_elo import DEFAULT_MLB_ELO, LiveMLBEloAdapter, STATE_SCHEMA_VERSION
    state_path = tmp_path / "elo.json"
    state_path.write_text(json.dumps({"schema_version": STATE_SCHEMA_VERSION, "ratings": DEFAULT_MLB_ELO,
                                      "history_count": 0, "history": [], "processed_game_pks": [],
                                      "last_update": None, "source": "Neutral 1500", "data_as_of": None}),
                          encoding="utf-8")
    games = []
    for index, (home, away) in enumerate([
        ("New York Yankees", "Boston Red Sox"), ("Chicago Cubs", "Chicago White Sox")
    ]):
        games.append({"gamePk": str(index + 1), "gameType": "R", "gameDate": f"2026-09-01T17:0{index}:00Z",
                      "status": {"abstractGameState": "Final"},
                      "teams": {"home": {"team": {"name": home}, "score": 2},
                                "away": {"team": {"name": away}, "score": 1}},
                      "linescore": {"teams": {"home": {"runs": 2}, "away": {"runs": 1}}}})
    adapter = LiveMLBEloAdapter(state_file=state_path)
    assert adapter.apply_official_games(games)["updated_games"] == 2
    repeat = LiveMLBEloAdapter(state_file=state_path)
    assert repeat.apply_official_games(games)["updated_games"] == 0


def test_elo_pipeline_persists_official_ledger_and_rechecks_postponed_game(tmp_path, monkeypatch):
    from scripts import update_mlb_elo

    def official_game(pk, day, status, *, game_type="R"):
        return {"gamePk": str(pk), "gameType": game_type, "gameDate": f"{day}T18:00:00Z",
                "status": status,
                "teams": {"home": {"team": {"name": "New York Yankees"}, "score": 3},
                          "away": {"team": {"name": "Boston Red Sox"}, "score": 2}},
                "linescore": {"teams": {"home": {"runs": 3}, "away": {"runs": 2}}}}

    postponed = official_game(2, "2026-09-25", {"abstractGameState": "Preview"})
    final_postponed = official_game(2, "2026-09-25", {"abstractGameState": "Final"})
    regular = official_game(1, "2026-09-24", {"abstractGameState": "Final"})
    spring = official_game(3, "2026-09-24", {"abstractGameState": "Preview"}, game_type="S")

    class FakeClient:
        def fetch_games(self, start, end):
            if start.isoformat() == "2026-09-24":
                return [regular, spring, postponed]
            if start.isoformat() == "2026-09-25":
                return [final_postponed]
            return []

    monkeypatch.setattr(update_mlb_elo, "MLBStatsApiClient", FakeClient)
    clock = [datetime(2026, 10, 1, tzinfo=timezone.utc)]
    root = tmp_path / "research"
    pipeline = ResearchPipeline(data_root=root, clock=lambda: clock[0])
    pipeline.config["model_update"]["bootstrap_start_date"] = "2026-09-24"
    pipeline.config["model_update"]["max_days_per_update"] = 7
    first_data = root / "runs" / "first" / "data"
    first_data.mkdir(parents=True)
    first = pipeline._stage_model_update(first_data)
    assert first["status"] == "WARMUP_IN_PROGRESS"
    assert first["pending_game_dates"] == ["2026-09-25"]
    ledger_path = root / "model_state" / "mlb_official_schedule_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert set(ledger["games"]) == {"1", "2", "3"}
    assert ledger["query_ranges"][0]["source_url"].startswith("https://statsapi.mlb.com/")

    clock[0] = datetime(2026, 10, 2, tzinfo=timezone.utc)
    second_data = root / "runs" / "second" / "data"
    second_data.mkdir(parents=True)
    second = pipeline._stage_model_update(second_data)
    assert second["pending_game_dates"] == []
    state = json.loads((root / "model_state" / "live_mlb_elo.json").read_text(encoding="utf-8"))
    assert set(state["processed_game_pks"]) == {"1", "2"}
    assert "3" not in state["processed_game_pks"]  # Spring training excluded by the declared model protocol.
    updated_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert updated_ledger["games"]["2"]["status"]["abstractGameState"] == "Final"


def test_missing_score_final_is_requeried_without_blocking_model_stage(tmp_path, monkeypatch):
    from scripts import update_mlb_elo
    complete = {"gamePk":"1","gameType":"R","gameDate":"2026-09-24T18:00:00Z",
                "status":{"abstractGameState":"Final"},
                "teams":{"home":{"team":{"name":"New York Yankees"},"score":3},
                         "away":{"team":{"name":"Boston Red Sox"},"score":2}}}
    missing = {"gamePk":"2","gameType":"R","gameDate":"2026-09-25T18:00:00Z",
               "status":{"abstractGameState":"Final"},
               "teams":{"home":{"team":{"name":"New York Yankees"}},
                        "away":{"team":{"name":"Boston Red Sox"}}}}
    class Client:
        fixed = False
        def fetch_games(self,start,end):
            if self.fixed:
                import copy
                final = copy.deepcopy(missing)
                final["teams"]["home"]["score"] = 4
                final["teams"]["away"]["score"] = 1
                return [final]
            return [complete,missing]
    client = Client()
    monkeypatch.setattr(update_mlb_elo,"MLBStatsApiClient",lambda:client)
    root = tmp_path/"research"
    pipeline = ResearchPipeline(data_root=root,clock=lambda:datetime(2026,10,1,tzinfo=timezone.utc))
    pipeline.config["model_update"]["bootstrap_start_date"] = "2026-09-24"
    stage = root/"runs/first/data";stage.mkdir(parents=True)
    result = pipeline._stage_model_update(stage)
    assert result["updated_games"] == 1
    assert result["incomplete_final_game_ids"] == ["2"]
    assert result["pending_game_dates"] == ["2026-09-25"]
    state_path = root/"model_state/live_mlb_elo.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state["processed_game_pks"]) == {"1"}
    assert state["data_as_of"].startswith("2026-09-24")
    client.fixed = True
    stage = root/"runs/second/data";stage.mkdir(parents=True)
    result = pipeline._stage_model_update(stage)
    assert result["incomplete_final_game_ids"] == []
    assert result["pending_game_dates"] == []
    assert set(json.loads(state_path.read_text(encoding="utf-8"))["processed_game_pks"]) == {"1","2"}


def test_postponed_mlb_game_reconciles_from_official_live_feed_and_replays_atomically(tmp_path, monkeypatch):
    """A postponed schedule stub must not hold Elo warmup after official final feed exists."""
    import copy
    import hashlib
    from scripts import update_mlb_elo
    from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter
    from core.research_pipeline import _mlb_normalize_live_feed

    artifact_root = Path(__file__).resolve().parents[1] / "artifacts" / "improvements_20261014"
    live_path = artifact_root / "mlb_778443_live.json"
    manifest_path = artifact_root / "mlb_778443_manifest.json"
    live_raw = live_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(live_raw).hexdigest() == manifest["sha256"]
    live_payload = json.loads(live_raw)

    postponed = {
        "gamePk": 778443,
        "gameType": "R",
        "gameDate": "2025-04-05T20:10:00Z",
        "officialDate": "2025-04-06",
        "rescheduleDate": "2025-04-06T17:35:00Z",
        "rescheduleGameDate": "2025-04-06",
        "status": {"abstractGameState": "Final", "codedGameState": "D", "detailedState": "Postponed"},
        "teams": {
            "away": {"team": {"id": 138, "name": "St. Louis Cardinals"}},
            "home": {"team": {"id": 111, "name": "Boston Red Sox"}},
        },
    }
    # A stale schedule score must never fill a hole in the authoritative live
    # linescore. These deliberately conflicting values guard against fallback.
    score_bearing_stub = copy.deepcopy(postponed)
    score_bearing_stub["teams"]["home"]["score"] = 99
    score_bearing_stub["teams"]["away"]["score"] = 98
    valid_normalized = _mlb_normalize_live_feed(
        live_payload, score_bearing_stub, observed_at_utc=manifest["observed_at_utc"]
    )
    assert valid_normalized["teams"]["home"]["score"] == 5
    assert valid_normalized["teams"]["away"]["score"] == 4

    def wrong_game_pk(payload):
        payload["gameData"]["game"]["pk"] = 999999

    def wrong_home_team(payload):
        payload["gameData"]["teams"]["home"]["id"] = 999

    def wrong_away_team(payload):
        payload["gameData"]["teams"]["away"]["id"] = 999

    def wrong_official_date(payload):
        payload["gameData"]["datetime"]["officialDate"] = "2025-04-07"

    def missing_official_date(payload):
        payload["gameData"]["datetime"].pop("officialDate", None)

    def wrong_game_type(payload):
        payload["gameData"]["game"]["type"] = "S"

    def still_postponed(payload):
        payload["gameData"]["status"].update({
            "abstractGameState": "Final", "codedGameState": "D", "detailedState": "Postponed"
        })

    def missing_home_runs(payload):
        payload["liveData"]["linescore"]["teams"]["home"].pop("runs", None)

    def missing_away_runs(payload):
        payload["liveData"]["linescore"]["teams"]["away"].pop("runs", None)

    for mutate in (wrong_game_pk, wrong_home_team, wrong_away_team, wrong_official_date,
                   missing_official_date, wrong_game_type,
                   still_postponed, missing_home_runs, missing_away_runs):
        invalid_payload = copy.deepcopy(live_payload)
        mutate(invalid_payload)
        with pytest.raises(ValueError):
            _mlb_normalize_live_feed(
                invalid_payload, score_bearing_stub, observed_at_utc=manifest["observed_at_utc"]
            )

    later_game = {
        "gamePk": 778444, "gameType": "R", "gameDate": "2025-04-08T18:10:00Z",
        "status": {"abstractGameState": "Final", "codedGameState": "F"},
        "teams": {
            "home": {"team": {"name": "New York Yankees"}, "score": 3},
            "away": {"team": {"name": "Boston Red Sox"}, "score": 2},
        },
        "linescore": {"teams": {"home": {"runs": 3}, "away": {"runs": 2}}},
    }
    root = tmp_path / "isolated-research"
    state_path = root / "model_state" / "live_mlb_elo.json"
    state_path.parent.mkdir(parents=True)
    LiveMLBEloAdapter(state_file=state_path).apply_official_games([later_game])
    ledger = {
        "schema": "mlb-official-ledger-v1",
        "source": "MLB Stats API schedule endpoint",
        "games": {"778443": postponed, "778444": later_game},
        "queried_through": "2025-04-12",
        "query_ranges": [],
    }
    ledger_path = root / "model_state" / "mlb_official_schedule_ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    progress_path = root / "model_state" / "live_mlb_elo_fetch_coverage.json"
    progress_path.write_text(json.dumps({
        "official_schedule_queried_through": "2025-04-12",
        "pending_game_dates": ["2025-04-05"],
        "pending_game_ids": ["778443"],
        "held_final_games": [],
    }), encoding="utf-8")

    class FakeClient:
        live_calls = 0

        def fetch_games(self, start, end):
            if start == end == date(2025, 4, 5):
                return [postponed]
            return []

        def fetch_live_game(self, game_pk):
            assert str(game_pk) == "778443"
            self.live_calls += 1
            if self.live_calls == 1:
                raise TimeoutError("temporary Stats API timeout")
            return {
                "payload": live_payload,
                "source_url": manifest["url"],
                "fetched_at_utc": manifest["observed_at_utc"],
                "sha256": manifest["sha256"],
            }

    client = FakeClient()
    monkeypatch.setattr(update_mlb_elo, "MLBStatsApiClient", lambda: client)
    pipeline = ResearchPipeline(data_root=root, clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc))
    pipeline.config["model_update"]["max_reschedule_live_feed_fetches_per_run"] = 20

    first_data = root / "runs" / "first" / "data"
    first_data.mkdir(parents=True)
    failed_fetch = pipeline._stage_model_update(first_data)
    assert failed_fetch["reschedule_reconciliation"]["status"] == "PARTIAL"
    assert "temporary Stats API timeout" in failed_fetch["reschedule_reconciliation"]["errors"][0]["error"]
    assert failed_fetch["pending_game_dates"] == ["2025-04-05"]
    assert not Path(str(state_path) + ".rebuild.tmp.json").exists()

    second_data = root / "runs" / "second" / "data"
    second_data.mkdir(parents=True)
    reconciled = pipeline._stage_model_update(second_data)
    assert reconciled["reschedule_reconciliation"]["reconciled_game_ids"] == ["778443"]
    assert reconciled["replayed_from_complete_source_ledger"] is True
    assert reconciled["late_final_replayed_count"] == 1
    assert reconciled["pending_game_dates"] == []

    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert {"778443", "778444"}.issubset(set(final_state["processed_game_pks"]))
    reconciled_history = next(row for row in final_state["history"] if row["game_pk"] == "778443")
    assert reconciled_history["date"] == "2025-04-06T17:35:00+00:00"
    assert reconciled_history["score"] == "5:4"
    assert not Path(str(state_path) + ".rebuild.tmp.json").exists()

    updated_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    evidence = updated_ledger["reschedule_reconciliations"]["778443"]
    assert evidence["live_feed_sha256"] == manifest["sha256"]
    assert evidence["live_feed_source_url"] == manifest["url"]
    assert evidence["live_feed_observed_at_utc"] == manifest["observed_at_utc"]
    assert evidence["normalized_game_date"] == "2025-04-06T17:35:00Z"
    assert evidence["normalized_home_team_id"] == 111
    assert evidence["normalized_away_team_id"] == 138
    assert evidence["final_score"] == "5:4"
    assert evidence["final_score_order"] == "home:away"


def test_model_failure_keeps_odds_collection_and_reporting_running(tmp_path, monkeypatch):
    now = datetime(2026,10,14,1,tzinfo=timezone.utc)
    FrozenDateTime.current = now
    monkeypatch.setattr("core.snapshot_logger.datetime",FrozenDateTime)
    pipeline = ResearchPipeline(data_root=tmp_path/"research",odds_adapter=FixtureOddsAdapter([_leg(now)]),
                                signal_hub=FixtureSignalHub(),clock=lambda:now,
                                model_updater=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("model source unavailable")))
    _offline_soccer_update(pipeline)
    result = pipeline.run()
    assert result["status"] == "FAILED"
    assert result["stages"]["model_update"]["status"] == "FAILED"
    assert result["stages"]["pregame_snapshots"]["status"] == "SUCCEEDED"
    assert result["stages"]["weekly_report"]["status"] == "SUCCEEDED"
    assert list((tmp_path/"research/reports").glob("weekly_*.json"))
