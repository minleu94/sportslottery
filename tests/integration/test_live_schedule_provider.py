#!/usr/bin/env python3
"""Integration test for ESPN Live Schedule Provider."""

import pytest
from integrations.schedules.espn_schedule import ESPNScheduleAdapter

pytestmark = pytest.mark.live


def test_live_espn_schedule_provider():
    """Verify live connection to ESPN public scoreboard API."""
    adapter = ESPNScheduleAdapter()
    events = adapter.fetch_live_events("MLB")

    # ESPN must return a valid list of events
    assert isinstance(events, list)
    assert len(events) > 0, "ESPN MLB scoreboard returned 0 events for today"

    first_event = events[0]
    assert "name" in first_event
    assert "date" in first_event
    assert len(first_event["name"]) > 3
