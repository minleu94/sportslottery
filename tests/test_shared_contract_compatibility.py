from datetime import datetime, timezone

import pytest

from core.contracts.common import PredictionSignal, TaiwanLeg, VerifiedExpertPick
from core.contracts.market import (
    MarketAlignmentRecord,
    MarketAlignmentStatus,
    MarketBenchmarkEvidence,
    MarketOddsSnapshot,
    MarketSelectionIdentity,
    canonical_market_event_id,
)
from integrations.common.models import (
    PredictionSignal as LegacyPredictionSignal,
    TaiwanLeg as LegacyTaiwanLeg,
    VerifiedExpertPick as LegacyVerifiedExpertPick,
)
from integrations.odds.market_models import (
    MarketAlignmentRecord as LegacyMarketAlignmentRecord,
    MarketAlignmentStatus as LegacyMarketAlignmentStatus,
    MarketBenchmarkEvidence as LegacyMarketBenchmarkEvidence,
    MarketOddsSnapshot as LegacyMarketOddsSnapshot,
)


def test_legacy_contract_imports_are_the_core_owned_types():
    assert LegacyPredictionSignal is PredictionSignal
    assert LegacyTaiwanLeg is TaiwanLeg
    assert LegacyVerifiedExpertPick is VerifiedExpertPick
    assert LegacyMarketAlignmentRecord is MarketAlignmentRecord
    assert LegacyMarketAlignmentStatus is MarketAlignmentStatus
    assert LegacyMarketBenchmarkEvidence is MarketBenchmarkEvidence
    assert LegacyMarketOddsSnapshot is MarketOddsSnapshot


def test_prediction_contract_serialization_keeps_legacy_shape():
    signal = LegacyPredictionSignal(
        source_id="test-model",
        source_name="Test Model",
        source_type="MODEL",
        event_id="tw-event-1",
        market="不讓分",
        selection="home",
        probability=0.61,
        timestamp="2026-11-02T12:00:00+00:00",
    )
    leg = LegacyTaiwanLeg(
        event_id="tw-event-1",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="home",
        taiwan_odds=1.9,
        side="主",
        start_time_utc="2026-11-02T15:00:00+00:00",
        line=None,
        signals=[signal],
    )

    payload = leg.to_dict()
    assert payload["event_id"] == payload["match_id"] == "tw-event-1"
    assert payload["market"] == payload["market_type"] == "不讓分"
    assert payload["odds"] == payload["taiwan_odds"] == 1.9
    assert payload["signals"][0]["source_id"] == "test-model"
    assert payload["signals"][0]["timestamp"] == "2026-11-02T12:00:00+00:00"


def test_market_contract_serialization_and_event_identity_remain_stable():
    quote = LegacyMarketOddsSnapshot(
        source_id="the_odds_api:pinnacle",
        source_type="BOOKMAKER",
        event_id="api-1",
        league="MLB",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        start_time_utc="2026-11-02T15:00:00+00:00",
        market_type="SPREAD",
        selection="home",
        decimal_odds=1.9,
        observed_at_utc="2026-11-02T12:00:00+00:00",
        retrieved_at_utc="2026-11-02T12:00:01+00:00",
        freshness_status="LIVE",
        line=-1.5,
    )
    alignment = LegacyMarketAlignmentRecord(
        status=LegacyMarketAlignmentStatus.MATCHED,
        taiwan_event_id="tw-1",
        taiwan_league="MLB",
        taiwan_market="讓分",
        taiwan_selection="Dodgers -1.5",
        taiwan_side="主",
        taiwan_line="-1.5",
        international_event_id="api-1",
        international_source_id=quote.source_id,
        international_market_type=quote.market_type,
        international_selection=quote.selection,
        international_line=quote.line,
        aligned_at_utc="2026-11-02T12:00:02+00:00",
    )

    assert quote.to_dict()["line"] == -1.5
    assert "raw_payload" not in quote.to_dict()
    assert alignment.to_dict()["status"] == "MATCHED"
    assert canonical_market_event_id("baseball", "MLB", "api-1", quote.start_time_utc) == (
        "baseball:mlb:api-1:2026-11-02T15:00:00+00:00"
    )


@pytest.mark.parametrize(
    ("left", "right", "matches"),
    [
        (MarketSelectionIdentity("SPREAD", "home", -1.5), MarketSelectionIdentity("SPREAD", "away", 1.5), True),
        (MarketSelectionIdentity("TOTAL", "over", 220.5), MarketSelectionIdentity("TOTAL", "under", 220.5), True),
        (MarketSelectionIdentity("SPREAD", "home", -1.5), MarketSelectionIdentity("SPREAD", "away", -1.5), False),
        (MarketSelectionIdentity("TOTAL", "over", 220.5), MarketSelectionIdentity("TOTAL", "under", 221.5), False),
    ],
)
def test_market_selection_contract_enforces_opposing_line_semantics(left, right, matches):
    assert left.opposite_outcome(right) is matches\n