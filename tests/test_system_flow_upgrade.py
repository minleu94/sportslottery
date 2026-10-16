"""Isolated offline integration flow covering signal, search, wallet and metrics."""
from datetime import datetime, timedelta, timezone

from core.parlay_engine import ParlayEngine
from core.snapshot_logger import PredictionSnapshotLogger
from core.odds_watcher import OddsWatcher
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.common.models import PredictionSignal, TaiwanLeg


class DeterministicSignalHub:
    """Offline signal source with explicit lineage and observation times."""
    def evaluate_taiwan_leg(self, leg):
        observed = datetime.now(timezone.utc) - timedelta(minutes=2)
        leg.signals = [
            PredictionSignal(
                source_id="model-a", source_name="Fixture model A", source_type="MODEL",
                event_id=leg.event_id, market=leg.market, selection=leg.selection,
                probability=.64, source_category="OPEN_SOURCE_ENGINE", independence_group="MODEL_A",
                freshness_status="FRESH", timestamp=observed.isoformat(), data_as_of=observed.isoformat(),
            ),
            PredictionSignal(
                source_id="model-b", source_name="Fixture model B", source_type="MODEL",
                event_id=leg.event_id, market=leg.market, selection=leg.selection,
                probability=.62, source_category="LOCAL_REIMPLEMENTATION", independence_group="MODEL_B",
                freshness_status="FRESH", timestamp=observed.isoformat(), data_as_of=observed.isoformat(),
            ),
        ]
        leg.signal_evidence = {
            "agreement": "HIGH", "evidence_quality": "HIGH", "independent_support_count": 2,
            "supporting_groups": ["MODEL_A", "MODEL_B"], "non_market_supports": 2,
            "model_fusion_groups": ["MODEL_A", "MODEL_B"], "excluded_model_ids": [],
            "consensus_probability": .63, "model_probability_raw": .63,
            "model_probability_calibrated": .63, "probability_status": "UNVALIDATED_MODEL_ESTIMATE",
            "model_provenances": [signal.to_dict() for signal in leg.signals],
            "publication_time_precision": "NOT_APPLICABLE", "verified_experts": [], "expert_count": 0,
        }
        leg.evidence_quality = "HIGH"
        leg.consensus_probability = .63
        leg.model_probability_raw = .63
        leg.model_probability_calibrated = .63
        return leg


def test_offline_signal_search_ticket_snapshot_settlement_metrics_flow(tmp_path):
    now = datetime.now(timezone.utc)
    # Keep the isolated quote within the watcher's 15-minute pre-start window.
    start = now + timedelta(minutes=10)
    odds_observed = now - timedelta(minutes=1)
    raw_matches = []
    for event_id, canonical, away, home in (
        ("evt-a", "MLB_20261012_CHC_CIN_220000", "芝加哥小熊", "辛辛那提紅人"),
        ("evt-b", "MLB_20261012_NYY_BOS_230000", "紐約洋基", "波士頓紅襪"),
    ):
        raw_matches.append({
            "match_id": event_id, "canonical_event_id": canonical, "sport": "baseball", "league": "MLB",
            "away_team": away, "home_team": home, "start_time_utc": start.isoformat(),
            "odds_scraped_at": odds_observed.isoformat(), "odds_status": "LIVE",
            "options": [{"market_type": "不讓分", "selection": "客勝", "side": "客", "odds": 2.0}],
        })

    engine = ParlayEngine(signal_hub=DeterministicSignalHub())
    recommendations = engine.search_parlays(raw_matches, min_odds=3.5, max_odds=4.5,
                                             min_legs=2, max_legs=2, signal_filter="strict")
    recommendation = recommendations["high_consensus"][0]
    assert recommendation["is_ready"] is True
    assert recommendation["total_independent_sources"] == 4

    db_path = tmp_path / "flow.sqlite3"
    wallet = WeeklyWalletManager(db_path=db_path)
    wallet.deposit_external(100, notes="isolated test funding")
    recorder = TicketRecorder(wallet=wallet)
    ticket = recorder.place_ticket(
        recommendation["legs"], stake=10, total_odds=recommendation["total_odds"],
        entry_mode="recommendation", idempotency_key="isolated-flow-1",
    )
    assert ticket["status"] == "OPEN"
    assert wallet.get_status()["weekly_staked"] == 10

    snapshot_logger = PredictionSnapshotLogger(tmp_path / "snapshots.jsonl")
    snapshots = [snapshot_logger.log_snapshot(leg) for leg in recommendation["raw_legs"]]
    assert all(snapshot["forward_validation_eligible"] for snapshot in snapshots)
    assert all(snapshot["probability_status"] == "UNVALIDATED_MODEL_ESTIMATE" for snapshot in snapshots)
    assert all(snapshot["model_probability"] == .63 for snapshot in snapshots)
    assert all(snapshot["crowd_votes"] is None for snapshot in snapshots)

    # Use an isolated odds-watch history and resolve the last pre-start
    # third-party observation with the full event/market/line identity.
    watcher = OddsWatcher(history_path=tmp_path / "odds_history.jsonl")
    for leg in recommendation["raw_legs"]:
        watcher.record_observation(
            event_id=leg.event_id, sport=leg.sport, league=leg.league,
            market=leg.market, selection=leg.selection, odds=2.05,
            observed_at=leg.odds_scraped_at, event_start=leg.start_time_utc,
            line=leg.line, canonical_event_id=leg.canonical_event_id,
        )

    for index, snapshot in enumerate(snapshots):
        won = index == 1
        close, close_status = watcher.get_closing_odds(
            event_id=snapshot["event_id"], sport=snapshot["sport"], league=snapshot["league"],
            market=snapshot["market"], selection=snapshot["selection"],
            event_start_iso=snapshot["event_start"], line=snapshot.get("line"),
            canonical_event_id=snapshot.get("canonical_event_id"),
        )
        assert close_status == "RECORDED" and close == 2.05
        settled = snapshot_logger.settle_prediction(
            snapshot["snapshot_id"], actual_outcome=won,
            settlement_status="WON" if won else "LOST", result_source="OFFLINE_FIXTURE",
            closing_odds=close, closing_odds_source="ODDS_WATCHER_LAST_PRESTART_OBSERVATION",
        )
        assert settled["settlement_status"] == ("WON" if won else "LOST")
        assert settled["brier_score"] is not None
        assert settled["closing_odds_source"] == "ODDS_WATCHER_LAST_PRESTART_OBSERVATION"

    recorder.settle_ticket(ticket["ticket_id"], won=False)
    metrics = snapshot_logger.compute_calibration_metrics()
    assert metrics["forward_eligible_count"] == 2
    assert metrics["settled_count"] == 2
    assert metrics["mean_brier_score"] is not None
    assert wallet.get_status()["weekly_wallet_balance"] == 90
