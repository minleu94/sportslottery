#!/usr/bin/env python3
"""Integration test for Open-source GitHub Model Adapters (Penaltyblog & Pybaseball)."""

import pytest
from integrations.common.models import TaiwanLeg
from integrations.models.penaltyblog_soccer_model import PenaltyblogSoccerAdapter
from integrations.models.pybaseball_mlb_model import PybaseballMLBAdapter

pytestmark = pytest.mark.live


def test_penaltyblog_soccer_model_live_execution(tmp_path):
    """Verify real execution of Penaltyblog goal expectancy calculation on a soccer TaiwanLeg."""
    adapter = PenaltyblogSoccerAdapter(cache_dir=str(tmp_path / "cache"))

    leg = TaiwanLeg(
        event_id="201",
        sport="soccer",
        league="英超",
        market="不讓分",
        selection="兵工廠客勝 (1.75)",
        taiwan_odds=1.75,
        start_time="PM 10:00",
        away_team="兵工廠",
        home_team="富勒姆",
        side="客",
    )

    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.source_id == "penaltyblog_poisson"
    assert sig.source_type == "MODEL"
    assert 0.05 <= sig.probability <= 0.95
    assert "github_repo" in sig.metadata
    assert sig.metadata["github_repo"] == "martineastwood/penaltyblog"


def test_pybaseball_mlb_model_live_execution(tmp_path):
    """Verify real execution of Pybaseball Pythagorean calculation on an MLB TaiwanLeg."""
    adapter = PybaseballMLBAdapter(cache_file=str(tmp_path / "espn_mlb_standings.json"))

    leg = TaiwanLeg(
        event_id="116",
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="釀酒人不讓分勝 (1.52)",
        taiwan_odds=1.52,
        start_time="AM 12:35",
        away_team="釀酒人",
        home_team="海盜",
        side="客",
    )

    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert sig.source_id == "pybaseball_mlb_model"
    assert sig.source_type == "MODEL"
    assert 0.05 <= sig.probability <= 0.95
    assert "github_repo" in sig.metadata
    assert sig.metadata["github_repo"] == "jldbc/pybaseball"
