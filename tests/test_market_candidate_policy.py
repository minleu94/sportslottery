from datetime import datetime, timedelta, timezone

import pytest

from core.market_candidate_policy import candidate_rejection_reason
from integrations.common.models import TaiwanLeg


@pytest.fixture
def valid_leg():
    now = datetime.now(timezone.utc)
    return TaiwanLeg(
        sport="baseball",
        league="MLB",
        event_id="playsport-mlb-001",
        home_team="Los Angeles Dodgers",
        away_team="San Diego Padres",
        market="不讓分",
        selection="Los Angeles Dodgers moneyline",
        side="主",
        taiwan_odds=1.9,
        odds_status="LIVE",
        start_time_utc=(now + timedelta(hours=2)).isoformat(),
    )


def _reason(leg):
    return candidate_rejection_reason(
        leg,
        "MLB",
        "h2h",
        market_to_api={"不讓分": "h2h"},
        query_key_resolver=lambda league: "baseball_mlb" if league.upper() == "MLB" else None,
    )


def test_complete_fresh_candidate_is_eligible(valid_leg):
    assert _reason(valid_leg) is None


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("odds_status", "STALE_CACHE", "TAIWAN_ODDS_NOT_FRESH"),
        ("start_time_utc", None, "INVALID_OR_MISSING_START_TIME"),
        ("home_team", "主隊", "MISSING_TEAMS"),
        ("taiwan_odds", 1.0, "INVALID_TAIWAN_ODDS"),
    ],
)
def test_candidate_policy_rejects_incomplete_or_stale_data(valid_leg, field, value, expected):
    setattr(valid_leg, field, value)
    assert _reason(valid_leg) == expected
