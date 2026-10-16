from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from core.shadow_parlay_logger import compute_parlay_fingerprint
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import PredictionSnapshotLogger
from core.strategy_version import STRATEGY_VERSION
from core.experiment_identity import build_experiment_identity
from core.strategy_version import get_strategy_metadata
from integrations.common.models import TaiwanLeg


def legs(eligible=True):
    return [{"event_id": "100", "canonical_event_id": "MLB-event-1", "sport": "baseball", "league": "MLB",
             "start_time_utc": "2026-10-13T00:00:00Z", "market": "大小", "side": "大", "selection": "大", "line": 8.5,
             "taiwan_odds": 2, "signal_evidence": {"forward_validation_eligible": eligible}}]


def test_same_day_distinct_events_have_distinct_parlay_fingerprints():
    first = legs()
    second = deepcopy(first)
    second[0]["canonical_event_id"] = "MLB-event-2"
    second[0]["start_time_utc"] = "2026-10-13T06:00:00Z"
    assert compute_parlay_fingerprint(first) != compute_parlay_fingerprint(second)


def test_concurrent_shadow_retry_stakes_once_and_excluded_paper_bets_are_separate(tmp_path):
    manager = ShadowPortfolioManager(tmp_path / "shadow.db")

    def place(_):
        return manager.place_shadow_ticket(legs(), 2, "TOP_HIGH", "10-25x", date_str="2026-10-12")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(place, range(4)))
    assert len({row["ticket_id"] for row in results}) == 1
    manager.settle_ticket(results[0]["ticket_id"], settlement_status="WON")
    # A retry cannot replace a resolved win with a loss.
    manager.settle_ticket(results[0]["ticket_id"], settlement_status="LOST")
    excluded = legs(False)
    excluded[0]["canonical_event_id"] = "excluded"
    manager.place_shadow_ticket(excluded, 2, "TOP_TARGET", "10-25x")
    summary = manager.get_portfolio_summary(strategy_version=STRATEGY_VERSION, eligible_only=True)
    assert summary["total_tickets_logged"] == 0
    assert summary["wins"] == 0
    assert summary["excluded_tickets"] == 2


def test_shadow_ticket_hash_and_snapshot_refs_are_required_for_qualified_summary(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = tmp_path / "prediction_snapshots.jsonl"
    logger = PredictionSnapshotLogger(ledger)
    manager = ShadowPortfolioManager(tmp_path / "shadow.db", snapshot_path=ledger)
    leg = TaiwanLeg(event_id="sealed-shadow", sport="baseball", league="MLB", market="不讓分",
                    selection="Home", taiwan_odds=2, start_time_utc=(now + timedelta(days=1)).isoformat(),
                    away_team="Away", home_team="Home", side="主",
                    odds_scraped_at=(now-timedelta(minutes=1)).isoformat(), odds_status="FRESH")
    leg.signal_evidence = {"probability_status": "MARKET_BASELINE_ONLY",
                           "publication_time_precision": "NOT_APPLICABLE"}
    snapshot = logger.log_snapshot(leg)
    leg_dict = leg.to_dict()
    leg_dict["signal_evidence"].update({"snapshot_id": snapshot["snapshot_id"],
                                        "forward_validation_eligible": snapshot["forward_validation_eligible"]})
    assert snapshot["forward_validation_eligible"] is True
    ticket = manager.place_shadow_ticket([leg_dict], 2, "TOP_HIGH", "10-25x", date_str="2026-10-13")
    qualified = manager.get_portfolio_summary(eligible_only=True)
    assert ticket["forward_validation_eligible"] is True
    assert qualified["total_tickets_logged"] == 1

    with sqlite3.connect(manager.db_path) as conn:
        stored = conn.execute("SELECT legs_json FROM shadow_tickets WHERE id = ?", (ticket["ticket_id"],)).fetchone()[0]
        changed = json.loads(stored)
        changed[0]["selection"] = "Away"
        conn.execute("UPDATE shadow_tickets SET legs_json = ? WHERE id = ?",
                     (json.dumps(changed, ensure_ascii=False), ticket["ticket_id"]))
    rejected = manager.get_portfolio_summary(eligible_only=True)
    assert rejected["total_tickets_logged"] == 0


def test_shadow_ticket_dedup_uses_experiment_identity_not_strategy_name(tmp_path):
    manager = ShadowPortfolioManager(tmp_path / "shadow.db", snapshot_path=tmp_path / "empty.jsonl")
    first = manager.place_shadow_ticket(legs(), 2, "TOP_HIGH", "10-25x", date_str="2026-10-13")
    metadata = get_strategy_metadata()
    variant_identity = build_experiment_identity(
        metadata, protocol_settings={"evidence_weights_hash": "c" * 64}
    )
    second = manager.place_shadow_ticket(legs(), 2, "TOP_HIGH", "10-25x", date_str="2026-10-13",
                                         experiment_identity=variant_identity)
    assert first["ticket_id"] != second["ticket_id"]
    assert first["experiment_id"] != second["experiment_id"]
    summary = manager.get_portfolio_summary(eligible_only=False)
    assert summary["total_tickets_logged"] == 2
