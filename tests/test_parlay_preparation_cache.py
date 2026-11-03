import copy

from core.parlay_engine import ParlaySearchResult
from integrations.common.models import TaiwanLeg
from server.routers import parlay as api


class FakeSignalHub:
    def __init__(self):
        self.weights_config = {"test": 1}
        self._cache_epoch = 0
        self.calls = 0

    def evaluate_taiwan_leg(self, leg):
        self.calls += 1
        enriched = copy.copy(leg)
        enriched.signal_evidence = {**(leg.signal_evidence or {}), "evaluated": True}
        return enriched


def _leg(scraped_at="2026-11-02T12:00:00+00:00", *, age=1.0, status="FRESH"):
    return TaiwanLeg(
        event_id="event-1", sport="baseball", league="MLB", market="不讓分",
        selection="主隊勝", taiwan_odds=1.8, away_team="A", home_team="B",
        odds_scraped_at=scraped_at, odds_age_minutes=age, odds_status=status,
        signal_evidence={"source_status": status, "odds_age_minutes": age},
    )


def _clear_cache():
    with api._parlay_prepared_lock:
        api._parlay_prepared_cache = None


def test_prepared_legs_are_reused_for_same_snapshot_and_refresh_source_age():
    _clear_cache()
    hub = FakeSignalHub()
    original = _leg(age=1.0)
    enriched, hit, _ = api._get_prepared_parlay_legs([original], ["3"], hub)
    assert not hit
    assert hub.calls == 1

    newer_age = _leg(age=1.2)
    reused, hit, _ = api._get_prepared_parlay_legs([newer_age], ["3"], hub)
    assert hit
    assert hub.calls == 1
    assert reused[0].odds_age_minutes == 1.2
    assert reused[0].signal_evidence["odds_age_minutes"] == 1.2
    assert reused[0].signal_evidence["evaluated"] is True


def test_prepared_cache_invalidates_on_odds_or_signal_configuration_change():
    _clear_cache()
    hub = FakeSignalHub()
    first = _leg()
    api._get_prepared_parlay_legs([first], ["3"], hub)

    changed_odds = copy.copy(first)
    changed_odds.taiwan_odds = 1.9
    _, hit, _ = api._get_prepared_parlay_legs([changed_odds], ["3"], hub)
    assert not hit

    hub.weights_config = {"test": 2}
    _, hit, _ = api._get_prepared_parlay_legs([changed_odds], ["3"], hub)
    assert not hit


def test_prepared_cache_bypasses_when_source_refresh_is_forced():
    _clear_cache()
    hub = FakeSignalHub()
    item = _leg()
    api._get_prepared_parlay_legs([item], ["3"], hub)
    _, hit, _ = api._get_prepared_parlay_legs([item], ["3"], hub, bypass_cache=True)
    assert not hit
    assert hub.calls == 2


def test_parlay_response_reports_stage_timings(monkeypatch):
    _clear_cache()
    hub = FakeSignalHub()

    class Adapter:
        def get_taiwan_legs(self, _alliances, force_refresh=False):
            return [_leg()]

    class Engine:
        def search_parlays(self, **_kwargs):
            return ParlaySearchResult(
                {"high_consensus": [], "aggressive": [], "moonshot": []},
                search_state={}, diagnostics={},
            )

    monkeypatch.setattr("server.service_registry.get_services", lambda: (Adapter(), hub, Engine(), None, None, None, None, None))
    response = api._execute_parlay_search(api.ParlaySearchRequest(target_odds=3.0))

    assert response["performance"]["raw_legs_count"] == 1
    assert response["performance"]["prepared_legs_cache_hit"] is False
    assert response["performance"]["total_ms"] >= response["performance"]["parlay_search_ms"]
    assert {"taiwan_fetch_ms", "signal_enrichment_ms", "parlay_search_ms", "response_format_ms"}.issubset(response["performance"])
