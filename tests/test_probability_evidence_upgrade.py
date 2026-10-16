import pytest

from core.edge_engine import EdgeEngine
from core.signal_hub import SignalHub
from integrations.common.models import PredictionSignal, TaiwanLeg


def model(source="model", probability=0.6, group="STATS", freshness="FRESH"):
    return PredictionSignal(source_id=source, source_name=source, source_type="MODEL", event_id="1", market="不讓分", selection="主", probability=probability,
        source_category="OPEN_SOURCE_ENGINE", independence_group=group, freshness_status=freshness, score=10, metadata={"configured_weight": 1})


def leg():
    return TaiwanLeg(event_id="1", sport="baseball", league="MLB", market="不讓分", selection="主", side="主", taiwan_odds=2)


def test_duplicate_lineage_has_no_new_probability_or_confidence_information():
    engine = EdgeEngine()
    first = engine.evaluate_leg(leg(), [model()])
    repeated = engine.evaluate_leg(leg(), [model(), model(), model("model_b", 0.9)])
    assert repeated.consensus_probability == first.consensus_probability
    assert repeated.details["independent_model_count"] == 0
    assert repeated.details["probability_status"] == "MARKET_BASELINE_ONLY"
    assert repeated.details["effective_sample_n"] == 0
    assert repeated.confidence_interval is None
    assert repeated.conservative_ev is None


def test_popularity_and_historical_expert_win_rate_are_not_event_probabilities():
    candidate = leg()
    expert = PredictionSignal(source_id="expert", source_name="expert", source_type="EXPERT", event_id="1", market="不讓分", selection="主", probability=0.99, score=99,
        source_category="VERIFIED_EXPERT", independence_group="PLAYSPORT_EXPERT")
    crowd = PredictionSignal(source_id="crowd", source_name="crowd", source_type="CROWD", event_id="1", market="不讓分", selection="主", probability=0.99, score=99,
        source_category="CROWD_CONSENSUS", independence_group="PLAYSPORT_CROWD")
    bare = EdgeEngine().evaluate_leg(candidate, [])
    human = EdgeEngine().evaluate_leg(candidate, [expert, crowd])
    assert bare.consensus_probability == human.consensus_probability
    assert human.details["probability_status"] == "MARKET_BASELINE_ONLY"


def test_complete_three_way_market_is_devigged_and_incomplete_market_is_not():
    candidate = TaiwanLeg(event_id="s", sport="soccer", league="英超", market="不讓分", selection="主", side="主", taiwan_odds=2.8,
        signal_evidence={"market_complete": True, "market_outcome_odds": {"主": 2.8, "客": 2.4, "和": 3.1}})
    evaluated = EdgeEngine().evaluate_leg(candidate, [])
    assert evaluated.market_fair_probability == pytest.approx((1 / 2.8) / (1 / 2.8 + 1 / 2.4 + 1 / 3.1))
    assert evaluated.details["market_fair_method"] == "COMPLETE_MARKET_PROPORTIONAL"
    candidate.signal_evidence["market_outcome_odds"].pop("和")
    incomplete = EdgeEngine().evaluate_leg(candidate, [])
    assert incomplete.market_fair_probability == 1 / 2.8
    assert incomplete.details["market_fair_method"] == "BREAKEVEN_BASELINE_NOT_DEVIGGED"


def test_unknown_or_stale_models_and_pitcher_names_cannot_create_high_support():
    candidate = leg()
    candidate.away_pitcher, candidate.home_pitcher = "Away pitcher", "Home pitcher"
    hub = SignalHub(expert_adapter=object(), crowd_adapter=object(), model_registry=object())
    evaluated = hub.synthesize_signals_for_leg(candidate, [model(freshness="UNKNOWN"), model("old", group="OTHER", freshness="STALE")])
    assert evaluated.evidence_quality == "INSUFFICIENT_SIGNAL"
    assert evaluated.signal_evidence["non_market_supports"] == 0
    assert evaluated.confidence_interval is None


def test_configured_weights_change_actual_model_fusion_and_original_market_survives():
    candidate = leg()
    candidate.signal_evidence = {"market_complete": True, "market_outcome_odds": {"主": 2, "客": 2}}
    lower, higher = model("a", 0.5, "A"), model("b", 0.8, "B")
    higher.metadata["configured_weight"] = 3
    hub = SignalHub(expert_adapter=object(), crowd_adapter=object(), model_registry=object())
    enriched = hub.synthesize_signals_for_leg(candidate, [lower, higher])
    assert enriched.model_probability_raw is None
    assert enriched.signal_evidence["model_candidate_probability_raw"] == pytest.approx((0.5 + 0.8 * 3) / 4)
    assert enriched.signal_evidence["probability_status"] == "MARKET_BASELINE_ONLY"
    repeated = hub.synthesize_signals_for_leg(enriched, [lower, higher])
    assert repeated.signal_evidence["market_complete"]
    assert repeated.signal_evidence["market_fair_method"] == "COMPLETE_MARKET_PROPORTIONAL"
