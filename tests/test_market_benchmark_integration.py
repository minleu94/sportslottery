from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.market_forward_pipeline import MarketForwardPipeline
from core.sharp_edge_engine import SharpEdgeEngine
from core.signal_hub import SignalHub
from integrations.common.models import TaiwanLeg
from integrations.odds.market_models import (
    MarketAlignmentRecord,
    MarketAlignmentStatus,
    MarketBenchmarkEvidence,
    MarketOddsSnapshot,
)


def _leg() -> TaiwanLeg:
    now = datetime.now(timezone.utc)
    return TaiwanLeg(
        sport="basketball",
        league="NBA",
        event_id="tw-event-1",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        market="不讓分",
        selection="Boston Celtics 不讓分勝",
        side="主",
        taiwan_odds=1.9,
        odds_status="LIVE",
        odds_scraped_at=now.isoformat(),
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
    )


def _benchmark(leg: TaiwanLeg) -> MarketBenchmarkEvidence:
    now = datetime.now(timezone.utc).isoformat()
    return MarketBenchmarkEvidence(
        taiwan_event_id=leg.event_id,
        taiwan_selection=leg.selection,
        canonical_event_id="basketball:nba:provider-event-1:2026-11-02T00:00:00+00:00",
        sport=leg.sport,
        league=leg.league,
        market_type="MONEYLINE",
        selection="home",
        line=None,
        source_id="the_odds_api:consensus",
        bookmaker_ids=["pinnacle"],
        raw_outcome_odds={"the_odds_api:pinnacle": {"home": 1.6, "away": 2.4}},
        market_observation_times={"the_odds_api:pinnacle": {"home": now, "away": now}},
        retrieved_at_utc=now,
        is_synthetic=False,
        devig_method="MULTIPLICATIVE",
        fair_probability=0.6,
        sharp_fair_probability=0.6,
        source_qualification="SHARP_QUALIFIED",
        complete=True,
        freshness_status="LIVE",
        eligible=True,
        sharp_qualified_source_ids=["the_odds_api:pinnacle"],
        bookmaker_evidence=[],
    )


def _quote(
    source_id: str, selection: str, odds: float, observed_at: str, *,
    market_type: str = "MONEYLINE", line: float | None = None, league: str = "NBA",
    event_id: str = "provider-event-1",
) -> MarketOddsSnapshot:
    now = datetime.now(timezone.utc)
    return MarketOddsSnapshot(
        source_id=source_id,
        source_type="BOOKMAKER",
        event_id=event_id,
        league=league,
        home_team="Boston Celtics",
        away_team="New York Knicks",
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
        market_type=market_type,
        selection=selection,
        decimal_odds=odds,
        observed_at_utc=observed_at,
        retrieved_at_utc=now.isoformat(),
        freshness_status="LIVE",
        line=line,
        is_synthetic=False,
    )


def test_signal_hub_uses_injected_market_baseline_once_and_keeps_it_out_of_signal_votes(tmp_path: Path):
    leg = _leg()
    sharp_adapter = MagicMock()
    hub = SignalHub(
        expert_adapter=MagicMock(get_expert_signal=lambda item: None),
        crowd_adapter=MagicMock(get_crowd_signal=lambda item: None),
        model_registry=MagicMock(evaluate_leg_across_models=lambda item: []),
        sharp_adapter=sharp_adapter,
        line_movement_tracker=MagicMock(analyze_leg_movement=lambda item, current_odds: None),
        splits_client=MagicMock(get_betting_splits=lambda league: []),
        config_path=tmp_path / "missing-evidence-weights.yaml",
    )

    enriched = hub.evaluate_taiwan_leg(leg, market_benchmark=_benchmark(leg))

    assert enriched.signal_evidence["market_fair_probability"] == pytest.approx(0.6)
    assert enriched.signal_evidence["market_benchmark_fair_probability"] == pytest.approx(0.6)
    assert enriched.signal_evidence["market_benchmark_ev_pct"] == pytest.approx(14.0)
    assert enriched.signal_evidence["expected_value"] == pytest.approx(0.14)
    assert enriched.signal_evidence["market_source_qualification"] == "SHARP_QUALIFIED"
    assert not any(signal.source_category == "SHARP_MARKET_BENCHMARK" for signal in enriched.signals)
    sharp_adapter.evaluate_leg.assert_not_called()


def test_parlay_sharp_engine_uses_only_validated_injected_sharp_evidence():
    leg = _leg()
    leg.signal_evidence["market_benchmark"] = _benchmark(leg).to_dict()
    engine = SharpEdgeEngine()

    result = engine.evaluate_leg_sharp_edge(leg)
    parlay = engine.evaluate_parlay_sharp_ev([leg], total_odds=1.9)

    assert result is not None
    assert result.sharp_fair_prob == pytest.approx(0.6)
    assert result.details["source_id"] == "the_odds_api:pinnacle"
    assert parlay["has_sharp_benchmark"] is True
    assert parlay["is_positive_ev"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_outcome_odds", None),
        ("market_observation_times", None),
        ("raw_outcome_odds", {"the_odds_api:pinnacle": {"home": 1.6, "away": "bad"}}),
        ("bookmaker_ids", ["draftkings"]),
    ],
)
def test_sharp_comparison_rejects_malformed_or_unqualified_quote_vectors(field, value):
    leg = _leg()
    benchmark = _benchmark(leg)
    setattr(benchmark, field, value)
    leg.signal_evidence["market_benchmark"] = benchmark.to_dict()

    assert SharpEdgeEngine().evaluate_leg_sharp_edge(leg) is None


def test_pipeline_benchmark_requires_same_book_complete_fresh_market(tmp_path: Path):
    now = datetime.now(timezone.utc)
    observed = now.isoformat()
    leg = _leg()
    pipeline = MarketForwardPipeline(
        odds_adapter=MagicMock(),
        odds_client=MagicMock(sharp_qualified_books=["pinnacle"]),
        signal_hub=MagicMock(),
        snapshot_logger=MagicMock(),
        settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )
    quotes = [
        _quote("the_odds_api:pinnacle", "home", 1.9, observed),
        _quote("the_odds_api:pinnacle", "away", 2.1, observed),
        _quote("the_odds_api:draftkings", "home", 1.8, observed),
    ]

    benchmark = pipeline._build_market_benchmark_evidence(
        leg, quotes[0], quotes, taiwan_odds=leg.taiwan_odds,
    )

    assert benchmark is not None
    assert benchmark.eligible is True
    assert benchmark.source_qualification == "SHARP_QUALIFIED"
    assert benchmark.sharp_qualified_source_ids == ["the_odds_api:pinnacle"]
    assert benchmark.bookmaker_ids == ["pinnacle"]
    assert benchmark.fair_probability == pytest.approx(0.525)
    assert benchmark.raw_outcome_odds["the_odds_api:pinnacle"] == {"home": 1.9, "away": 2.1}


def test_pipeline_does_not_mix_counterpart_odds_between_books(tmp_path: Path):
    now = datetime.now(timezone.utc)
    observed = now.isoformat()
    leg = _leg()
    pipeline = MarketForwardPipeline(
        odds_adapter=MagicMock(),
        odds_client=MagicMock(sharp_qualified_books=["pinnacle"]),
        signal_hub=MagicMock(),
        snapshot_logger=MagicMock(),
        settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )
    quotes = [
        _quote("the_odds_api:pinnacle", "home", 1.9, observed),
        _quote("the_odds_api:draftkings", "away", 2.1, observed),
    ]

    assert pipeline._build_market_benchmark_evidence(
        leg, quotes[0], quotes, taiwan_odds=leg.taiwan_odds,
    ) is None


@pytest.mark.parametrize(
    ("market", "side", "line", "primary_selection", "primary_line", "other_selection", "other_line", "other_market"),
    [
        ("讓分", "主", "-1.5", "home", -1.5, "away", 1.5, "SPREAD"),
        ("大小", "大", "220.5", "over", 220.5, "under", 220.5, "TOTAL"),
    ],
)
def test_spread_and_total_benchmarks_keep_their_line_contract(
    tmp_path: Path, market, side, line, primary_selection, primary_line,
    other_selection, other_line, other_market,
):
    now = datetime.now(timezone.utc).isoformat()
    leg = _leg()
    leg.market = market
    leg.side = side
    leg.line = line
    leg.selection = "selected Taiwan outcome"
    quotes = [
        _quote("the_odds_api:pinnacle", primary_selection, 1.91, now,
               market_type=other_market, line=primary_line),
        _quote("the_odds_api:pinnacle", other_selection, 1.91, now,
               market_type=other_market, line=other_line),
        # A draw price in another market must not turn a spread/total into 1X2.
        _quote("the_odds_api:pinnacle", "draw", 3.2, now, market_type="MONEYLINE"),
    ]
    pipeline = MarketForwardPipeline(
        odds_adapter=MagicMock(), odds_client=MagicMock(sharp_qualified_books=["pinnacle"]),
        signal_hub=MagicMock(), snapshot_logger=MagicMock(), settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(), summary_path=tmp_path / f"{other_market}-summary.json",
    )

    benchmark = pipeline._build_market_benchmark_evidence(
        leg, quotes[0], quotes, taiwan_odds=leg.taiwan_odds,
    )

    assert benchmark is not None
    assert benchmark.market_type == other_market
    assert benchmark.complete is True
    assert benchmark.eligible is True
    assert benchmark.source_qualification == "SHARP_QUALIFIED"
    assert set(benchmark.raw_outcome_odds["the_odds_api:pinnacle"]) == {primary_selection, other_selection}


def test_soccer_moneyline_uses_complete_three_way_benchmark(tmp_path: Path):
    now = datetime.now(timezone.utc).isoformat()
    leg = _leg()
    leg.sport = "soccer"
    leg.league = "EPL"
    leg.market = "不讓分"
    leg.side = "主"
    leg.selection = "Home win"
    quotes = [
        _quote("the_odds_api:pinnacle", "home", 2.1, now, league="EPL"),
        _quote("the_odds_api:pinnacle", "draw", 3.2, now, league="EPL"),
        _quote("the_odds_api:pinnacle", "away", 3.8, now, league="EPL"),
    ]
    pipeline = MarketForwardPipeline(
        odds_adapter=MagicMock(), odds_client=MagicMock(sharp_qualified_books=["pinnacle"]),
        signal_hub=MagicMock(), snapshot_logger=MagicMock(), settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(), summary_path=tmp_path / "soccer-summary.json",
    )

    benchmark = pipeline._build_market_benchmark_evidence(
        leg, quotes[0], quotes, taiwan_odds=leg.taiwan_odds,
    )

    assert benchmark is not None
    assert benchmark.fair_probability == pytest.approx(1 / 2.1 / (1 / 2.1 + 1 / 3.2 + 1 / 3.8))
    assert set(benchmark.raw_outcome_odds["the_odds_api:pinnacle"]) == {"home", "draw", "away"}


def test_pipeline_injects_validated_market_evidence_before_snapshot(tmp_path: Path):
    now = datetime.now(timezone.utc)
    leg = _leg()
    leg.home_team = "Boston Celtics"
    leg.away_team = "New York Knicks"
    quotes = [
        _quote("the_odds_api:pinnacle", "home", 1.9, now.isoformat()),
        _quote("the_odds_api:pinnacle", "away", 2.1, now.isoformat()),
    ]
    quotes[0].start_time_utc = leg.start_time_utc
    quotes[1].start_time_utc = leg.start_time_utc
    adapter = MagicMock(get_taiwan_legs=lambda leagues, **kwargs: [leg])
    odds_client = MagicMock(
        scheduled_markets="h2h", markets="h2h", regions="us",
        sharp_qualified_books=["pinnacle"],
    )
    odds_client.get_source_status.return_value = {
        "requests_used_this_month": 0,
        "request_metrics": {"api_requests": 0, "cache_hits": 0, "coalesced_requests": 0},
    }
    odds_client.fetch_market_odds.return_value = quotes
    signal_hub = MagicMock()

    def evaluate(item: TaiwanLeg, *, market_benchmark: MarketBenchmarkEvidence):
        item.signal_evidence["market_benchmark"] = market_benchmark.to_dict()
        item.signal_evidence["market_fair_probability"] = market_benchmark.fair_probability
        item.expected_value = market_benchmark.fair_probability * item.taiwan_odds - 1.0
        return item

    signal_hub.evaluate_taiwan_leg.side_effect = evaluate
    alignment = MarketAlignmentRecord(
        status=MarketAlignmentStatus.MATCHED,
        taiwan_event_id=leg.event_id,
        taiwan_league=leg.league,
        taiwan_market=leg.market,
        taiwan_selection=leg.selection,
        taiwan_side=leg.side,
        taiwan_line=leg.line,
        international_event_id=quotes[0].event_id,
        international_source_id=quotes[0].source_id,
        international_market_type="MONEYLINE",
        international_selection="home",
        international_line=None,
        aligned_at_utc=now.isoformat(),
    )
    aligner = MagicMock(align_leg_with_candidates=lambda item, candidates: (quotes[0], alignment))
    snapshot_logger = MagicMock()
    snapshot_logger.log_snapshot.return_value = {
        "forward_validation_eligible": True, "settlement_status": "PENDING",
    }
    pipeline = MarketForwardPipeline(
        odds_adapter=adapter,
        odds_client=odds_client,
        signal_hub=signal_hub,
        aligner=aligner,
        fair_engine=None,
        snapshot_logger=snapshot_logger,
        settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"], automated=True)

    passed = signal_hub.evaluate_taiwan_leg.call_args.kwargs["market_benchmark"]
    assert passed.eligible is True
    assert passed.source_qualification == "SHARP_QUALIFIED"
    assert result["complete_market_benchmark_count"] == 1
    assert result["sharp_qualified_count"] == 1
    snapshot_leg = snapshot_logger.log_snapshot.call_args.args[0]
    assert snapshot_leg.signal_evidence["market_fair_probability"] == pytest.approx(0.525)
    assert snapshot_leg.expected_value == pytest.approx(0.525 * leg.taiwan_odds - 1.0)


def test_stale_candidate_in_a_mixed_batch_never_reaches_alignment_or_snapshot(tmp_path: Path):
    now = datetime.now(timezone.utc)
    valid = _leg()
    invalid = _leg()
    invalid.event_id = "stale-taiwan-quote"
    invalid.odds_status = "STALE_CACHE"
    adapter = MagicMock()
    adapter.get_taiwan_legs.return_value = [valid, invalid]
    client = MagicMock(
        scheduled_markets="h2h", markets="h2h", regions="us",
        sharp_qualified_books=["pinnacle"],
    )
    client.get_source_status.return_value = {
        "requests_used_this_month": 0,
        "request_metrics": {"api_requests": 0, "cache_hits": 0, "coalesced_requests": 0},
    }
    client.fetch_market_odds.return_value = []
    unmatched = MarketAlignmentRecord(
        status=MarketAlignmentStatus.UNMATCHED,
        taiwan_event_id=valid.event_id,
        taiwan_league=valid.league,
        taiwan_market=valid.market,
        taiwan_selection=valid.selection,
        taiwan_side=valid.side,
        taiwan_line=valid.line,
        international_event_id=None,
        international_source_id=None,
        international_market_type=None,
        international_selection=None,
        international_line=None,
        aligned_at_utc=now.isoformat(),
        rejection_code="ERR_NO_INTERNATIONAL_QUOTES",
    )
    aligner = MagicMock()
    aligner.align_leg_with_candidates.side_effect = lambda item, quotes: (None, unmatched)
    hub = MagicMock()
    hub.evaluate_taiwan_leg.side_effect = lambda item: item
    logger = MagicMock()
    logger.log_snapshot.return_value = {"forward_validation_eligible": False}
    pipeline = MarketForwardPipeline(
        odds_adapter=adapter,
        odds_client=client,
        signal_hub=hub,
        aligner=aligner,
        snapshot_logger=logger,
        settlement_engine=MagicMock(),
        evaluation_engine=MagicMock(),
        summary_path=tmp_path / "summary.json",
    )

    result = pipeline.run_market_snapshot_cycle(leagues=["NBA"])

    assert result["total_legs_processed"] == 2
    assert result["valid_candidate_count"] == 1
    assert result["candidate_rejection_counts"]["TAIWAN_ODDS_NOT_FRESH"] == 1
    client.fetch_market_odds.assert_called_once()
    aligner.align_leg_with_candidates.assert_called_once()
    assert aligner.align_leg_with_candidates.call_args.args[0] is valid
    hub.evaluate_taiwan_leg.assert_called_once_with(valid)
    logger.log_snapshot.assert_called_once_with(valid)
