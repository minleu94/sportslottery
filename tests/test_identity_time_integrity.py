from datetime import date

from core.identity.event_matcher import EventMatcher
from core.identity.timezone import parse_playsport_time_to_utc


def test_unknown_time_is_not_fabricated_and_year_rollover_is_correct():
    assert parse_playsport_time_to_utc("今日賽程") is None
    assert parse_playsport_time_to_utc("invalid") is None
    assert parse_playsport_time_to_utc("PM 99:99") is None
    assert parse_playsport_time_to_utc("01/01 AM 00:30", date(2026, 12, 31)).startswith("2026-12-31T16:30")
    assert parse_playsport_time_to_utc("2026/10/12 AM 06:00", date(2026, 10, 12)).startswith("2026-10-11T22:00")


def test_doubleheader_and_reused_local_id_have_separate_event_identity():
    matcher = EventMatcher()
    kwargs = dict(sport="baseball", league="MLB", away_name="洋基", home_name="道奇")
    first = matcher.match_or_create(**kwargs, start_time_utc="2026-10-12T10:00:00Z", taiwan_event_id="100")
    second = matcher.match_or_create(**kwargs, start_time_utc="2026-10-12T15:00:00Z", taiwan_event_id="101")
    tomorrow = matcher.match_or_create(**kwargs, start_time_utc="2026-10-13T10:00:00Z", taiwan_event_id="100")
    assert len({first.canonical_event_id, second.canonical_event_id, tomorrow.canonical_event_id}) == 3
    assert matcher.match_or_create(**kwargs, start_time_utc=None) is None


def test_cross_source_schedule_rounding_can_match_but_conflicting_provider_ids_cannot():
    matcher = EventMatcher()
    kwargs = dict(sport="baseball", league="MLB", away_name="小熊", home_name="紅人")
    first = matcher.match_or_create(**kwargs, start_time_utc="2026-10-12T10:00:00Z", taiwan_event_id="100")
    rounded = matcher.match_or_create(**kwargs, start_time_utc="2026-10-12T10:30:00Z")
    distinct = matcher.match_or_create(**kwargs, start_time_utc="2026-10-12T10:35:00Z", taiwan_event_id="101")
    assert first.canonical_event_id == rounded.canonical_event_id
    assert distinct.canonical_event_id != first.canonical_event_id
