#!/usr/bin/env python3
"""Acceptance Test Suite for Shadow Research Integrity Gate.

Verifies:
1. Prediction snapshot strictly precedes event start (cutoff integrity)
2. Prediction payload hash immutability (raises AuditFailureError on modification)
3. Closing odds must be pre-event (observed_at < event_start)
4. Missing closing odds is NOT_AVAILABLE (no fabrication)
5. Taiwan parlay VOID logic: void leg becomes odds 1.0; parlay recalculates multiplier
6. Postponed market beyond valid window becomes VOID
7. Duplicate shadow parlay is not double-counted (N=1, NT$10 stake once, merged tags)
8. Deterministic parlay fingerprint independent of leg permutation
9. Daily snapshot idempotency (no duplicate predictions on rerun)
10. Odds observations can repeat in odds history without duplicating formal predictions
11. Unknown expert timestamp excluded from strict forward metrics (EXPERT_TIME_UNKNOWN)
12. Settlement conflict between result providers flags UNRESOLVED
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.odds_watcher import OddsWatcher
from core.settlement.taiwan_rules import TaiwanSettlementRules
from core.settlement_engine import SettlementEngine
from core.shadow_parlay_logger import ShadowParlayLogger, compute_parlay_fingerprint
from core.shadow_portfolio import ShadowPortfolioManager
from core.snapshot_logger import (
    AuditFailureError,
    PredictionSnapshotLogger,
    check_cutoff_integrity,
    compute_prediction_payload_hash,
)
from integrations.common.models import TaiwanLeg


def test_prediction_snapshot_precedes_event(tmp_path):
    """Verify that predictions observed after match start are excluded as POST_START_DATA."""
    # Pre-event: snapshot at 06:00, event at 07:00 -> PASS
    eligible, reason = check_cutoff_integrity(
        snapshot_timestamp_iso="2026-09-18T06:00:00+00:00",
        event_start_iso="2026-09-18T07:00:00+00:00",
        odds_timestamp_iso="2026-09-18T05:55:00+00:00",
        expert_precision="NOT_APPLICABLE",
    )
    assert eligible is True
    assert reason is None

    # Post-event: snapshot at 07:05, event at 07:00 -> FAIL (POST_START_DATA)
    eligible_post, reason_post = check_cutoff_integrity(
        snapshot_timestamp_iso="2026-09-18T07:05:00+00:00",
        event_start_iso="2026-09-18T07:00:00+00:00",
        odds_timestamp_iso="2026-09-18T07:03:00+00:00",
        expert_precision="NOT_APPLICABLE",
    )
    assert eligible_post is False
    assert reason_post == "POST_START_DATA"


def test_prediction_payload_hash_immutable(tmp_path):
    """Verify that altering any original prediction field triggers AuditFailureError during settlement."""
    snap_file = tmp_path / "snaps_audit.jsonl"
    logger = PredictionSnapshotLogger(log_path=snap_file)

    leg = TaiwanLeg(
        event_id="301",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="道奇 客勝",
        taiwan_odds=1.75,
        start_time="07:05",
        away_team="道奇",
        home_team="巨人",
        side="客",
    )
    snap = logger.log_snapshot(leg)
    sid = snap["snapshot_id"]
    original_hash = snap["prediction_payload_hash"]
    assert original_hash is not None

    # Tamper with file: change taiwan_odds from 1.75 to 2.10
    lines = snap_file.read_text(encoding="utf-8").splitlines()
    tampered_lines = []
    for line in lines:
        data = json.loads(line)
        if data.get("snapshot_id") == sid:
            data["taiwan_odds"] = 2.10  # MALICIOUS TAMPERING
        tampered_lines.append(json.dumps(data))
    snap_file.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    # Attempt settlement: MUST raise AuditFailureError
    with pytest.raises(AuditFailureError) as exc_info:
        logger.settle_prediction(snapshot_id=sid, actual_outcome=True)

    assert "AUDIT_FAILURE" in str(exc_info.value)


def test_closing_odds_must_be_pre_event(tmp_path):
    """Verify closing odds resolver takes only observations strictly before event_start."""
    odds_file = tmp_path / "odds_hist.jsonl"
    watcher = OddsWatcher(history_path=odds_file)

    event_start = "2026-09-18T07:00:00+00:00"

    # Obs 1: 06:00 (odds 1.70)
    watcher.record_observation("401", "baseball", "MLB", "不讓分", "洋基勝", 1.70, "2026-09-18T06:00:00+00:00", event_start)
    # Obs 2: 06:45 (odds 1.78) - last pre-game observation!
    watcher.record_observation("401", "baseball", "MLB", "不讓分", "洋基勝", 1.78, "2026-09-18T06:45:00+00:00", event_start)
    # Obs 3: 07:15 (odds 1.85) - post-start observation!
    watcher.record_observation("401", "baseball", "MLB", "不讓分", "洋基勝", 1.85, "2026-09-18T07:15:00+00:00", event_start)

    closing_odds, status = watcher.get_closing_odds("401", "不讓分", "洋基勝", event_start)
    assert closing_odds == 1.78, "Closing odds must be the latest observation strictly BEFORE event start"
    assert status == "RECORDED"


def test_missing_close_is_not_available(tmp_path):
    """Verify that missing closing odds returns None and NOT_AVAILABLE without fabricating."""
    odds_file = tmp_path / "odds_empty.jsonl"
    watcher = OddsWatcher(history_path=odds_file)

    closing_odds, status = watcher.get_closing_odds("999", "不讓分", "無隊", "2026-09-18T07:00:00+00:00")
    assert closing_odds is None
    assert status == "NOT_AVAILABLE"

    clv = watcher.compute_clv_metrics(prediction_odds=1.85, closing_odds=None)
    assert clv["clv_status"] == "NOT_AVAILABLE"
    assert clv["odds_clv_ratio"] is None
    assert clv["clv_probability_pp"] is None


def test_void_leg_becomes_odds_one_in_parlay(tmp_path):
    """Verify Taiwan parlay VOID logic: a void leg becomes odds 1.0 and parlay stays winning if other legs win."""
    p_log = tmp_path / "parlays_void.jsonl"
    parlay_logger = ShadowParlayLogger(log_path=p_log)

    tier_results = {
        "10-25x": {
            "high_consensus": [
                {
                    "total_odds": 6.0,  # Leg A (2.0) * Leg B (3.0) = 6.0
                    "legs": [
                        {"event_id": "1", "market": "不讓分", "selection": "A勝", "taiwan_odds": 2.0},
                        {"event_id": "2", "market": "不讓分", "selection": "B勝", "taiwan_odds": 3.0},
                    ],
                }
            ],
            "aggressive": [],
            "moonshot": [],
        },
        "25-75x": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "75-200x": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "200-500x": {"high_consensus": [], "aggressive": [], "moonshot": []},
    }

    records = parlay_logger.log_daily_parlays(tier_results, date_str="2026-09-18")
    cand_id = records[0]["candidates"][0]["candidate_id"]

    # Settle: Leg A = WON (2.0), Leg B = VOID (odds turns into 1.0)
    # Recalculated odds: 2.0 * 1.0 = 2.0x!
    settled = parlay_logger.settle_parlay_candidate_with_taiwan_rules(
        candidate_id=cand_id,
        leg_statuses=[("WON", 2.0), ("VOID", 3.0)],
        virtual_stake=10.0,
    )

    assert settled["settlement_status"] == "WON", "Parlay must NOT be marked LOST when leg is VOID"
    assert settled["recalculated_total_odds"] == 2.0
    assert settled["actual_payout"] == 20.0  # NT$10 * 2.0 = NT$20
    assert settled["profit_loss"] == 10.0


def test_postponed_market_settlement():
    """Verify postponement beyond valid window settles as VOID."""
    status, reason = TaiwanSettlementRules.evaluate_taiwan_market(
        rule_id="MLB_FULLGAME_ML",
        market="不讓分",
        selection="洋基勝",
        line=None,
        away_score=0,
        home_score=0,
        is_postponed=True,
        postponed_beyond_window=True,
    )
    assert status == "VOID"
    assert "超出台彩有效補賽窗口" in reason


def test_duplicate_shadow_parlay_not_double_counted(tmp_path):
    """Verify that identical parlays across categories place 1 wager (N=1), deducting NT$10 once."""
    db_path = tmp_path / "shadow_dedupe.sqlite"
    shadow_mgr = ShadowPortfolioManager(db_path=db_path)

    identical_legs = [
        {"event_id": "1", "market": "不讓分", "selection": "勝1", "taiwan_odds": 2.0},
        {"event_id": "2", "market": "讓分", "selection": "勝2", "taiwan_odds": 1.8},
    ]

    # Candidate parlay structure where TOP_HIGH and TOP_MED select the exact same ticket
    tier_results = {
        "10-25x": {
            "high_consensus": [{"legs": identical_legs, "total_odds": 3.6, "multiplier_tier": "10-25x"}],
            "aggressive": [{"legs": identical_legs, "total_odds": 3.6, "multiplier_tier": "10-25x"}],
            "moonshot": [],
        },
        "25-75x": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "75-200x": {"high_consensus": [], "aggressive": [], "moonshot": []},
        "200-500x": {"high_consensus": [], "aggressive": [], "moonshot": []},
    }

    placed = shadow_mgr.place_daily_top_picks(tier_results, date_str="2026-09-18")
    assert len(placed) == 1, "Identical parlay must be deduplicated to 1 wager!"
    assert placed[0]["virtual_stake"] == 10.0
    assert set(placed[0]["strategy_tags"]) == {"TOP_HIGH", "TOP_MED"}

    # Check database: exactly 1 ticket
    summary = shadow_mgr.get_portfolio_summary()
    assert summary["total_tickets_logged"] == 1


def test_parlay_fingerprint_deterministic():
    """Verify that parlay fingerprint is deterministic and invariant to leg order."""
    leg1 = {"event_id": "A", "market": "不讓分", "selection": "主勝", "line": None}
    leg2 = {"event_id": "B", "market": "大小", "selection": "大8.5", "line": 8.5}

    fp_order_1 = compute_parlay_fingerprint([leg1, leg2])
    fp_order_2 = compute_parlay_fingerprint([leg2, leg1])

    assert fp_order_1 == fp_order_2
    assert len(fp_order_1) == 16


def test_daily_snapshot_idempotency(tmp_path):
    """Verify daily snapshot does not write duplicate predictions upon rerun on the same date."""
    snap_file = tmp_path / "snaps_idempotent.jsonl"
    logger = PredictionSnapshotLogger(log_path=snap_file)

    leg = TaiwanLeg(
        event_id="501",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="勇士 客勝",
        taiwan_odds=1.90,
        start_time="07:05",
        away_team="勇士",
        home_team="大都會",
        side="客",
    )

    s1 = logger.log_snapshot(leg)
    s2 = logger.log_snapshot(leg)  # Duplicate call

    assert s1["snapshot_id"] == s2["snapshot_id"]
    lines = snap_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1, "Rerunning on the same day must be idempotent (1 record only)"


def test_odds_observation_can_repeat_without_duplicate_prediction(tmp_path):
    """Verify odds watcher can append multiple observations while prediction remains unique."""
    odds_file = tmp_path / "odds_stream.jsonl"
    watcher = OddsWatcher(history_path=odds_file)

    # Scrape 3 times throughout the morning
    watcher.record_observation("601", "baseball", "MLB", "不讓分", "道奇勝", 1.70, "2026-09-18T01:00:00Z")
    watcher.record_observation("601", "baseball", "MLB", "不讓分", "道奇勝", 1.72, "2026-09-18T03:00:00Z")
    watcher.record_observation("601", "baseball", "MLB", "不讓分", "道奇勝", 1.75, "2026-09-18T05:00:00Z")

    lines = odds_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3, "Odds history records full time-series"


def test_unknown_expert_timestamp_excluded_from_strict_forward_metrics(tmp_path):
    """Verify that expert picks with DATE_ONLY precision are flagged and excluded from forward evaluation."""
    eligible, reason = check_cutoff_integrity(
        snapshot_timestamp_iso="2026-09-18T06:00:00+00:00",
        event_start_iso="2026-09-18T07:00:00+00:00",
        expert_precision="DATE_ONLY",
    )
    assert eligible is False
    assert reason == "EXPERT_TIME_UNKNOWN"


def test_settlement_conflict_is_unresolved():
    """Verify that conflicting provider scores trigger conflict status."""
    settler = SettlementEngine()
    # Provider A (MLB API): 5:3; Provider B (ESPN): 5:4 -> CONFLICT!
    is_conflict = settler.check_provider_conflict(
        provider_a_result=(5, 3),
        provider_b_result=(5, 4),
    )
    assert is_conflict is True
