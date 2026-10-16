from datetime import datetime, timedelta, timezone

import pytest

from core.bet_validation import assess_leg, validate_recommendation_legs

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def valid_leg():
    return {"event_id": "100", "canonical_event_id": "event-1", "market": "不讓分", "taiwan_odds": 2,
            "away_team": "客隊甲", "home_team": "主隊乙",
            "start_time_utc": (NOW + timedelta(hours=1)).isoformat(), "odds_scraped_at": NOW.isoformat(), "odds_status": "FRESH"}


@pytest.mark.parametrize("patch,reason", [
    ({"taiwan_odds": float("nan")}, "ODDS_INVALID"),
    ({"start_time_utc": None}, "START_TIME_UNKNOWN"),
    ({"start_time_utc": "12:00"}, "START_TIME_UNKNOWN"),
    ({"start_time_utc": "2026-10-12T13:00:00"}, "START_TIME_UNKNOWN"),
    ({"start_time_utc": NOW.isoformat()}, "EVENT_STARTED"),
    ({"odds_scraped_at": (NOW - timedelta(minutes=16)).isoformat()}, "ODDS_STALE"),
    ({"odds_scraped_at": None}, "ODDS_TIME_UNKNOWN"),
    ({"odds_scraped_at": (NOW + timedelta(minutes=3)).isoformat()}, "ODDS_TIME_FUTURE"),
    ({"market": "大小", "line": None}, "LINE_UNKNOWN"),
    ({"away_team": "客隊", "home_team": "主隊"}, "EVENT_IDENTITY_INCOMPLETE"),
    ({"away_team": "", "home_team": "主隊乙"}, "EVENT_IDENTITY_INCOMPLETE"),
    ({"away_team": "同一隊", "home_team": "同一隊"}, "EVENT_IDENTITY_INCOMPLETE"),
])
def test_ready_requires_observable_pre_game_odds(patch, reason):
    candidate = {**valid_leg(), **patch}
    assert reason in assess_leg(candidate, NOW)["reasons"]
    with pytest.raises(ValueError):
        validate_recommendation_legs([candidate], NOW)


def test_one_canonical_event_cannot_be_repeated_under_two_local_ids():
    assert assess_leg(valid_leg(), NOW)["is_ready"]
    with pytest.raises(ValueError, match="同場"):
        validate_recommendation_legs([valid_leg(), {**valid_leg(), "event_id": "101"}], NOW)
