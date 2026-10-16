from datetime import datetime, timedelta, timezone

from core.parlay_engine import ParlayEngine
from integrations.common.models import TaiwanLeg


def test_search_diagnostics_cover_every_eligible_option():
    now = datetime.now(timezone.utc)
    legs = [TaiwanLeg(
        event_id=str(event), sport="baseball", league="MLB", market="不讓分",
        selection=str(option), taiwan_odds=odds, away_team="洋基", home_team="紅襪",
        side="客", odds_scraped_at=now.isoformat(), odds_status="FRESH",
        start_time_utc=(now + timedelta(hours=1)).isoformat(),
        evidence_quality="LOW", signal_evidence={"agreement":"LOW", "evidence_quality":"LOW"},
    ) for event in (1, 2) for option, odds in enumerate((1.5, 2.0, 3.0))]
    engine = ParlayEngine(signal_hub=object())
    diagnostics = {}
    result = engine.search_parlays(legs, min_odds=1.05, max_odds=500, signal_filter="wild",
                                  diagnostics=diagnostics)
    assert diagnostics["quality_option_count"] == 6
    assert diagnostics["search_option_count"] == 6
    assert diagnostics["search_event_count"] == 2
    assert diagnostics["checked_combinations"] == 9
    assert diagnostics["odds_matching_combinations"] == 9
    assert diagnostics["search_complete"] is True
    assert diagnostics["max_matches_pool_applied"] is False
    assert len(result["aggressive"]) == 9
    assert result["high_consensus"] == []
    assert result["moonshot"] == []


def test_empty_pool_has_explicit_zero_diagnostics():
    diagnostics = {}
    ParlayEngine(signal_hub=object()).search_parlays([], diagnostics=diagnostics)
    assert diagnostics["search_event_count"] == diagnostics["checked_combinations"] == 0
    assert diagnostics["search_complete"] is True


def test_search_covers_events_beyond_legacy_pool_and_reports_budget_exhaustion():
    now = datetime.now(timezone.utc)
    legs = [TaiwanLeg(
        event_id=f"event-{event}", sport="baseball", league="MLB", market="不讓分",
        selection=f"selection-{event}", taiwan_odds=2.0, away_team=f"away-{event}", home_team=f"home-{event}",
        side="客", odds_scraped_at=now.isoformat(), odds_status="FRESH",
        start_time_utc=(now + timedelta(hours=1)).isoformat(), evidence_quality="LOW",
        signal_evidence={"agreement": "LOW", "evidence_quality": "LOW"},
    ) for event in range(17)]
    engine = ParlayEngine(signal_hub=object())
    complete = {}
    engine.search_parlays(legs, min_odds=3.9, max_odds=4.1, min_legs=2, max_legs=2,
                          signal_filter="wild", diagnostics=complete)
    assert complete["search_event_count"] == 17
    assert complete["search_option_count"] == 17
    assert complete["checked_combinations"] == 136
    assert complete["odds_matching_combinations"] == 136
    assert complete["search_complete"] is True

    partial = {}
    engine.search_parlays(legs, min_odds=3.9, max_odds=4.1, min_legs=2, max_legs=2,
                          signal_filter="wild", search_budget=5, diagnostics=partial)
    assert partial["budget_exhausted"] is True
    assert partial["search_complete"] is False
    assert partial["search_status"] == "BUDGET_EXHAUSTED"
    assert partial["visited_nodes"] == 5


def test_odds_interval_pruning_proves_empty_search_complete():
    now = datetime.now(timezone.utc)
    legs = [TaiwanLeg(
        event_id=f"event-{event}", sport="baseball", league="MLB", market="不讓分",
        selection=f"selection-{event}", taiwan_odds=3.0, away_team=f"away-{event}", home_team=f"home-{event}",
        side="客", odds_scraped_at=now.isoformat(), odds_status="FRESH",
        start_time_utc=(now + timedelta(hours=1)).isoformat(), evidence_quality="LOW",
        signal_evidence={"agreement": "LOW", "evidence_quality": "LOW"},
    ) for event in range(4)]
    diagnostics = {}
    result = ParlayEngine(signal_hub=object()).search_parlays(
        legs, min_odds=10, max_odds=20, min_legs=2, max_legs=2,
        signal_filter="wild", diagnostics=diagnostics,
    )
    assert result == {"high_consensus": [], "aggressive": [], "moonshot": []}
    assert diagnostics["search_complete"] is True
    assert diagnostics["checked_combinations"] == 0
    assert diagnostics["odds_pruned_nodes"] > 0


def test_pruned_search_matches_independent_exhaustive_odds_counts():
    import itertools,math
    now=datetime.now(timezone.utc)
    odds_by_event=[(1.3,2.1,3.7),(1.6,2.9),(1.4,4.2),(1.8,2.2,5.1)]
    legs=[TaiwanLeg(event_id=f"event-{i}",sport="baseball",league="MLB",market="不讓分",
                   selection=f"selection-{j}",side="客",taiwan_odds=odds,
                   away_team=f"Away-{i}",home_team=f"Home-{i}",odds_status="FRESH",
                   odds_scraped_at=now.isoformat(),start_time_utc=(now+timedelta(hours=1)).isoformat(),
                   evidence_quality="LOW",signal_evidence={"agreement":"LOW","evidence_quality":"LOW"})
          for i,prices in enumerate(odds_by_event) for j,odds in enumerate(prices)]
    expected=sum(8<=math.prod(prices)<=23 for size in (2,3)
                 for events in itertools.combinations(range(4),size)
                 for prices in itertools.product(*(odds_by_event[i] for i in events)))
    diagnostic={}
    ParlayEngine(signal_hub=object()).search_parlays(legs,min_odds=8,max_odds=23,min_legs=2,max_legs=3,
                                                    signal_filter="wild",diagnostics=diagnostic)
    assert diagnostic["search_complete"]
    assert diagnostic["odds_matching_combinations"]==expected
