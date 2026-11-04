import threading
from unittest.mock import MagicMock

from core.contracts.common import TaiwanLeg
from server import service_registry
from server.responses import (
    ForwardEvaluationResponse,
    LegsResponse,
    MarketResearchSummaryResponse,
    ParlaySearchResponse,
    RadarResponse,
    ResearchAnalyticsResponse,
)
from server.routers import market as market_routes
from server.routers import parlay as parlay_routes
from server.routers import research as research_routes
from server.schemas import ParlaySearchRequest


def test_radar_and_legs_responses_match_frontend_contract(monkeypatch):
    leg = TaiwanLeg(
        event_id="tw-event-contract",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="主勝",
        taiwan_odds=1.91,
        away_team="Away Team",
        home_team="Home Team",
        side="主",
    )
    adapter = MagicMock()
    adapter.get_taiwan_legs.return_value = [leg]
    adapter.get_source_status.return_value = {"1": {"status": "LIVE"}}
    radar = MagicMock()
    radar.get_radar_summary.return_value = [{
        "code": "MLB",
        "name": "MLB",
        "icon": "⚾",
        "status": "GREEN",
        "status_text": "盤口開放",
        "light_emoji": "🟢",
        "game_count": 1,
        "taiwan_market_count": 1,
        "schedule_source_status": "LIVE",
        "games": [{"event_id": "tw-event-contract"}],
    }]
    monkeypatch.setattr(
        service_registry,
        "get_services",
        lambda: (adapter, MagicMock(), MagicMock(), radar, MagicMock(), MagicMock(), MagicMock(), MagicMock()),
    )

    radar_body = RadarResponse.model_validate(market_routes.get_radar()).model_dump(mode="json")
    legs_body = LegsResponse.model_validate(
        market_routes.get_legs(alliances=None, force_refresh=False, limit=1000, _session=None)
    ).model_dump(mode="json")

    assert radar_body["radar"][0]["schedule_source_status"] == "LIVE"
    assert radar_body["status_counts"] == {"GREEN": 1, "YELLOW": 0, "RED": 0}
    assert radar_body["total_legs"] == 1
    assert legs_body["total"] == legs_body["returned"] == 1
    assert legs_body["legs"][0]["display_league"].endswith("(MLB)")
    assert legs_body["legs"][0]["event_id"] == "tw-event-contract"


def test_parlay_response_exposes_tier_and_hides_internal_raw_legs(monkeypatch):
    from core.contracts.common import TaiwanLeg

    leg = TaiwanLeg(
        event_id="tw-event-parlay",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="主勝",
        taiwan_odds=1.91,
        away_team="Away Team",
        home_team="Home Team",
        side="主",
        signal_evidence={
            "is_market_synthetic": False,
            "probability_status": "MARKET_BASELINE_ONLY",
            "consensus_probability": 0.65,
            "expected_value_pct": -27.9,
            "consensus_ratio": 0.92,
            "vote_count": 120,
        },
    )
    adapter = MagicMock(get_taiwan_legs=lambda *_args, **_kwargs: [leg])
    signal_hub = MagicMock()
    signal_hub.weights_config = {}
    signal_hub._cache_epoch = 0
    signal_hub.evaluate_taiwan_leg.side_effect = lambda item: item
    parlay_engine = MagicMock()
    # Other concurrency tests intentionally replace this semaphore with a full
    # queue. Give this response-shape test isolated search controls.
    monkeypatch.setattr(parlay_routes, "_parlay_search_inflight", {})
    monkeypatch.setattr(parlay_routes, "_parlay_search_capacity", threading.BoundedSemaphore(6))
    monkeypatch.setattr(parlay_routes, "_parlay_search_slots", threading.BoundedSemaphore(2))

    def search_parlays(*, diagnostics, **_kwargs):
        diagnostics.update(search_status="COMPLETE", search_complete=True, evaluated_combinations=3)
        return {
            "high_consensus": [{
                "candidate_id": "candidate-1",
                "legs_count": 2,
                "parlay_name": "2 串 1",
                "total_odds": 1.55,
                "total_odds_exact": 1.554,
                "joint_probability": 0.4485,
                "parlay_expected_value": -0.30303,
                "parlay_ev_pct": -30.3,
                "credible_value_basis": False,
                "credible_value_status": "UNVERIFIED",
                "joint_probability_sources": ["UNVERIFIED_ESTIMATE", "UNVERIFIED_ESTIMATE"],
                "has_sharp_benchmark": False,
                "is_positive_ev": False,
                "legs": [leg, leg],
                "raw_legs": ["internal-only"],
            }],
            "aggressive": [],
            "moonshot": [],
        }

    parlay_engine.search_parlays.side_effect = search_parlays
    monkeypatch.setattr(
        service_registry,
        "get_services",
        lambda: (adapter, signal_hub, parlay_engine, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()),
    )

    response = parlay_routes.search_parlays(
        ParlaySearchRequest(target_odds=10.0, min_legs=2, max_legs=2, force_refresh=True),
        _session=None,
    )
    body = ParlaySearchResponse.model_validate(response).model_dump(mode="json")

    recommendation = body["tiers"]["high_consensus"][0]
    assert recommendation["tier"] == "high_consensus"
    assert recommendation["parlay_id"] == "candidate-1"
    assert recommendation["legs"][0]["event_id"] == "tw-event-parlay"
    assert recommendation["legs_count"] == len(recommendation["legs"]) == 2
    assert recommendation["total_odds_exact"] == 1.554
    assert recommendation["joint_probability"] == 0.4485
    assert recommendation["parlay_ev_pct"] == -30.3
    assert recommendation["credible_value_status"] == "UNVERIFIED"
    assert recommendation["legs"][0]["consensus_probability"] == 0.65
    assert recommendation["legs"][0]["signal_evidence"]["consensus_ratio"] == 0.92
    assert recommendation["legs"][0]["expected_value_pct"] == -27.9
    assert "raw_legs" not in recommendation
    assert body["performance"]["prepared_legs_cache_hit"] is False


def test_research_responses_match_frontend_contract(monkeypatch, tmp_path):
    analytics = {
        "total_snapshots": 3,
        "cohort": {"sample_size": 2, "observations": [], "audit": {"input_count": 3}},
        "agreement": {},
        "ev_data": {},
        "crowd_data": {},
        "expert_data": {},
        "shadow_portfolio": {"status": "EMPTY"},
    }
    snapshots = {
        "total_count": 3,
        "settled_count": 1,
        "forward_eligible_count": 1,
    }
    forward_evaluation = {
        "sample_size": 1,
        "status": "INSUFFICIENT_EVIDENCE",
    }
    pipeline = MagicMock()
    pipeline.get_research_status_summary.return_value = {
        "live_status": "SYNTHETIC_FIXTURE",
        "live_status_scope": "ODDS_API_SOURCE_STATUS_ONLY",
        "the_odds_api": {"status": "SYNTHETIC"},
        "alignment": {"status": "NO_RECORDED_CYCLE"},
        "scheduler": None,
        "snapshots": snapshots,
        "forward_evaluation": forward_evaluation,
        "as_of_utc": "2026-11-02T00:00:00+00:00",
    }
    scheduler = MagicMock(get_status=lambda: {"enabled": False})
    research_routes._analytics_cache = None
    research_routes._analytics_cache_mtime = 0
    research_routes._analytics_cache_time = 0
    monkeypatch.setattr(
        service_registry,
        "get_services",
        lambda: (
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            MagicMock(
                iter_snapshots=lambda: iter([1, 2, 3]),
                log_path=tmp_path / "snapshots.jsonl",
            ),
            MagicMock(
                forward_cohort=lambda _snaps: analytics["cohort"],
                evaluate_agreement_buckets=lambda _snaps: analytics["agreement"],
                evaluate_ev_buckets=lambda _snaps: analytics["ev_data"],
                evaluate_crowd_buckets=lambda _snaps: analytics["crowd_data"],
                evaluate_expert_metrics=lambda _snaps: analytics["expert_data"],
            ),
            MagicMock(get_portfolio_summary=lambda: analytics["shadow_portfolio"]),
        ),
    )
    monkeypatch.setattr(
        "core.market_forward_pipeline.MarketForwardPipeline",
        lambda: pipeline,
    )
    monkeypatch.setattr(market_routes, "get_market_scheduler", lambda: scheduler)

    analytics_body = ResearchAnalyticsResponse.model_validate(
        research_routes.get_research_analytics()
    ).model_dump(mode="json")
    market_summary_body = MarketResearchSummaryResponse.model_validate(
        market_routes.get_market_research_summary()
    ).model_dump(mode="json")

    assert analytics_body["total_snapshots"] == 3
    assert analytics_body["cohort"]["sample_size"] == 2
    assert market_summary_body["live_status_scope"] == "ODDS_API_SOURCE_STATUS_ONLY"
    assert market_summary_body["snapshots"]["forward_eligible_count"] == 1
    assert market_summary_body["forward_evaluation"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert market_summary_body["scheduler"]["enabled"] is False


def test_forward_evaluation_response_matches_frontend_contract(monkeypatch):
    metrics = {
        "sample_size": 0,
        "brier_score": None,
        "log_loss": None,
        "clv_mean_pct": None,
        "settled_roi_pct": None,
        "roi_ci_95": None,
        "brier_ci_95": None,
        "pnl_drawdown_amount": None,
        "win_rate_pct": None,
        "status": "INSUFFICIENT_EVIDENCE",
        "bet_count": 0,
        "simulated_roi_pct": None,
        "simulated_roi_ci_95": None,
        "simulated_bet_count": 0,
    }
    report = {
        "evaluation_scope": "MLB",
        "as_of_utc": "2026-11-02T00:00:00+00:00",
        "sample_size": 0,
        "paired_sample_size": 0,
        "taiwan_market_baseline": metrics,
        "international_sharp_benchmark": metrics,
        "active_model_strategy": metrics,
        "delta_roi_vs_taiwan_base_pp": None,
        "delta_roi_vs_sharp_benchmark_pp": None,
        "delta_brier_vs_sharp_benchmark": None,
        "delta_brier_ci_95": None,
        "champion_source": "TAIWAN_MARKET_BASELINE",
        "acceptance_gate_qualified": False,
        "status": "SHADOW_MODE_ACCUMULATING",
        "shadow_mode_recommendation": "MAINTAIN_SHADOW_MODE",
        "international_market_benchmark": metrics,
        "market_paired_sample_size": 0,
        "sharp_paired_sample_size": 0,
        "delta_brier_vs_market_benchmark": None,
        "delta_brier_market_ci_95": None,
        "data_quality_status": "INSUFFICIENT_UNIQUE_ELIGIBLE_EVENTS",
        "evaluation_protocol_status": "NOT_ENOUGH_EVENTS_TO_ASSESS",
        "statistical_evidence_status": "NOT_ESTABLISHED",
    }

    class FakeReport:
        def to_dict(self):
            return report

    class FakeEngine:
        def evaluate_cohort(self, snapshots, scope_name):
            assert snapshots == []
            assert scope_name == "MLB"
            return FakeReport()

    monkeypatch.setattr(market_routes, "ForwardEvaluationEngine", FakeEngine)
    monkeypatch.setattr(
        market_routes,
        "PredictionSnapshotLogger",
        lambda: MagicMock(get_all_snapshots=lambda: []),
    )

    body = ForwardEvaluationResponse.model_validate(
        market_routes.get_forward_evaluation_report(scope="MLB")
    ).model_dump(mode="json")

    assert body["evaluation_scope"] == "MLB"
    assert body["international_market_benchmark"]["sample_size"] == 0
    assert body["taiwan_market_baseline"]["pnl_drawdown_amount"] is None
    assert body["statistical_evidence_status"] == "NOT_ESTABLISHED"
