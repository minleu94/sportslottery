"""Read-only project review probes. All writes use temporary databases/files.

These assertions document current defects, not desired behavior.
Run: python artifacts/review_20261012_checks.py
"""
from __future__ import annotations

import gc
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.edge_engine import EdgeEngine
from core.parlay_engine import ParlayEngine
from core.snapshot_logger import PredictionSnapshotLogger, check_cutoff_integrity
from core.ticket_recorder import TicketRecorder
from core.wallet import WeeklyWalletManager
from integrations.common.models import PredictionSignal, TaiwanLeg
from integrations.models.external.live_mlb_elo import LiveMLBEloAdapter


def leg(event: str, quality: str = "LOW", **kwargs) -> TaiwanLeg:
    defaults = dict(
        event_id=event, sport="baseball", league="MLB", market="不讓分",
        selection="道奇 主勝", taiwan_odds=4.0, away_team="洋基",
        home_team="道奇", side="主", evidence_quality=quality,
        signal_evidence={"agreement": quality, "non_market_supports": 1},
    )
    defaults.update(kwargs)
    return TaiwanLeg(**defaults)


def main() -> None:
    outcomes = {}
    with TemporaryDirectory(prefix="sportslottery_review_") as tmp:
        root = Path(tmp)

        wallet = WeeklyWalletManager(root / "placement.sqlite")
        wallet.deposit_external(200)
        recorder = TicketRecorder(wallet=wallet)
        with sqlite3.connect(recorder.db_path) as conn:
            conn.execute("CREATE TRIGGER fail_ticket BEFORE INSERT ON tickets BEGIN SELECT RAISE(ABORT, 'simulated insert failure'); END")
        try:
            recorder.place_ticket([{"league": "MLB", "odds": 2}], 20, 2)
        except sqlite3.IntegrityError:
            pass
        status = wallet.get_status()
        assert status["weekly_wallet_balance"] == 180 and recorder.list_tickets() == []
        outcomes["failed_placement_debits_without_ticket"] = {
            "wallet": status["weekly_wallet_balance"], "tickets": 0,
        }

        wallet2 = WeeklyWalletManager(root / "settlement.sqlite")
        wallet2.deposit_external(200)
        recorder2 = TicketRecorder(wallet=wallet2)
        ticket = recorder2.place_ticket([{"league": "MLB", "odds": 2}], 20, 2)
        with sqlite3.connect(recorder2.db_path) as conn:
            conn.execute("CREATE TRIGGER fail_settlement BEFORE UPDATE OF status ON tickets BEGIN SELECT RAISE(ABORT, 'simulated settlement failure'); END")
        for _ in range(2):
            try:
                recorder2.settle_ticket(ticket["ticket_id"], won=True)
            except sqlite3.IntegrityError:
                pass
        assert wallet2.get_status()["prize_pool"] == 80
        assert recorder2.list_tickets()[0]["status"] == "OPEN"
        outcomes["failed_settlement_retry_duplicates_credit"] = {"prize_pool": 80, "ticket_status": "OPEN", "expected_payout": 40}

        wallet3 = WeeklyWalletManager(root / "concurrency.sqlite")
        wallet3.deposit_external(200)
        original_status = wallet3.get_status
        rendezvous = Barrier(2)

        def synchronized_status():
            snapshot = original_status()
            rendezvous.wait(timeout=10)
            return snapshot

        with patch.object(wallet3, "get_status", side_effect=synchronized_status):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(wallet3.stake_bet, 150, f"T{i}") for i in range(2)]
                for job in jobs:
                    job.result()
        state3 = original_status()
        assert state3["weekly_staked"] == 150 and state3["lifetime_staked"] == 300
        outcomes["concurrent_stakes_exceed_cap_and_lose_state_update"] = {
            "weekly_staked": 150, "ledger_staked": 300, "wallet": state3["weekly_wallet_balance"],
        }

        engine = ParlayEngine(signal_hub=object())
        result = engine.search_parlays([leg("A"), leg("B")], min_odds=10, max_odds=20, signal_filter="strict")
        assert result["high_consensus"] and all(l["evidence_quality"] == "LOW" for l in result["high_consensus"][0]["legs"])
        outcomes["strict_filter_and_high_consensus_silently_relax"] = {"leg_qualities": [l["evidence_quality"] for l in result["high_consensus"][0]["legs"]]}

        stale = [leg("C", odds_status="STALE_CACHE"), leg("D", odds_status="STALE_CACHE")]
        result_stale = engine.search_parlays(stale, min_odds=10, max_odds=20, signal_filter="wild")
        assert result_stale["aggressive"][0]["is_ready"] is False
        recorder3 = TicketRecorder(wallet=wallet3)
        recorder3.place_ticket(result_stale["aggressive"][0]["legs"], 10, 16)
        outcomes["ticket_recorder_accepts_stale_odds"] = True

        past = [leg("E", start_time_utc="2020-01-01T00:00:00Z"), leg("F", start_time_utc="2020-01-01T00:00:00Z")]
        past_result = engine.search_parlays(past, min_odds=10, max_odds=20, signal_filter="wild")
        assert past_result["aggressive"][0]["is_ready"] is True
        outcomes["past_events_still_marked_ready"] = True

        elo_file = root / "missing_elo_state.json"
        elo = LiveMLBEloAdapter(state_file=elo_file)
        signal = elo.evaluate_leg(leg("G"))
        assert not elo_file.exists() and signal.freshness_status == "LIVE" and signal.quality_label == "MODEL_HIGH_QUALITY"
        outcomes["elo_without_history_marked_live_high_quality"] = {"probability": signal.probability, "freshness": signal.freshness_status, "quality": signal.quality_label, "data_as_of": signal.data_as_of}

        cutoff = check_cutoff_integrity("2026-10-12T10:00:00Z", "AM 06:40")
        assert cutoff == (True, None)
        outcomes["invalid_start_time_passes_forward_validation"] = list(cutoff)

        snapshot_logger = PredictionSnapshotLogger(log_path=root / "snapshots.jsonl")
        snap = snapshot_logger.log_snapshot(leg("H", start_time_utc="2099-01-01T00:00:00Z"))
        settled = snapshot_logger.settle_prediction(snap["snapshot_id"], actual_outcome=False)
        assert settled["settlement_status"] == "WON" and settled["actual_outcome"] is False
        outcomes["losing_outcome_defaults_to_won_status"] = {"settlement_status": settled["settlement_status"], "actual_outcome": settled["actual_outcome"]}

        market_leg = leg("I", taiwan_odds=2.0)
        model = PredictionSignal(source_id="example", source_name="Example", source_type="MODEL", source_category="OPEN_SOURCE_ENGINE", independence_group="SAME_DATA", event_id="I", market="不讓分", selection="主勝", probability=0.6)
        edge = EdgeEngine()
        single = edge.evaluate_leg(market_leg, signals=[model])
        duplicated = edge.evaluate_leg(market_leg, signals=[model, model])
        assert duplicated.confidence_interval[0] > single.confidence_interval[0]
        outcomes["duplicate_model_signal_increases_claimed_precision"] = {"single_interval": single.confidence_interval, "duplicated_interval": duplicated.confidence_interval}

        # sqlite3 connection context managers commit/rollback but do not close.
        # Release local/temporary connections before Windows directory cleanup.
        conn.close()
        gc.collect()

    print(json.dumps(outcomes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
