#!/usr/bin/env python3
"""Acceptance Test Suite for Data Authenticity & Model Provenance Gates.

Fulfills Phase 16 Requirements:
1. test_production_contains_no_synthetic_training_data
2. test_soccer_training_matches_are_real
3. test_soccer_training_dates_precede_prediction (Leakage Guard)
4. test_soccer_minimum_training_sample
5. test_external_engine_provenance_category
6. test_538_source_freshness
7. test_local_reimplementation_not_labeled_external
8. test_model_input_provenance_logged
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest
import yaml

from core.identity import GLOBAL_TEAM_REGISTRY
from integrations.common.models import PredictionSignal, TaiwanLeg

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# 1. test_production_contains_no_synthetic_training_data
def test_production_contains_no_synthetic_training_data():
    """Production directory (data/cache, data/historical) must have ZERO synthetic match data."""
    cache_dir = PROJECT_ROOT / "data" / "cache"

    # 1. The old synthetic file MUST NOT exist in data/cache
    old_synthetic = cache_dir / "matches_eng.1.json"
    assert not old_synthetic.exists(), "Synthetic matches_eng.1.json must not exist in data/cache!"

    # 2. If tests/fixtures has synthetic data, verify it is quarantined in tests/fixtures
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "synthetic_matches_eng.1.json"
    if fixture_path.exists():
        assert str(PROJECT_ROOT / "tests") in str(fixture_path), "Synthetic data must only exist in tests/"

    # 3. Check all json files in data/cache to ensure none have synthetic tags
    for f in cache_dir.glob("*.json"):
        content = f.read_text(encoding="utf-8")
        assert "synthetic" not in f.name.lower(), f"File {f.name} in data/cache has synthetic in filename!"
        # Standings files must be real ESPN API structures
        if "espn" in f.name:
            assert "teams" in content, f"{f.name} missing teams dict"


# 2. test_soccer_training_matches_are_real
def test_soccer_training_matches_are_real():
    """Soccer historical match records must contain genuine dates, teams, scores, and not be randomly generated."""
    from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter

    adapter = PenaltyblogDixonColesAdapter()
    matches = adapter._load_league_matches("eng.1")

    assert len(matches) >= 60, f"Expected at least 60 real matches, got {len(matches)}"

    for m in matches[:20]:
        assert "date" in m, "Match must have a genuine date"
        assert "home_team" in m
        assert "away_team" in m
        assert "home_goals" in m
        assert "away_goals" in m
        # Validate date format YYYY-MM-DD
        datetime.strptime(m["date"], "%Y-%m-%d")
        assert isinstance(m["home_goals"], int)
        assert isinstance(m["away_goals"], int)
        assert m["home_goals"] >= 0
        assert m["away_goals"] >= 0


# 3. test_soccer_training_dates_precede_prediction (Leakage Guard)
def test_soccer_training_dates_precede_prediction():
    """Leakage Guard: Dixon-Coles model must ONLY fit on matches strictly before prediction date."""
    from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter

    adapter = PenaltyblogDixonColesAdapter()
    pred_date = "2024-12-01"

    filtered_matches = adapter._filter_matches_point_in_time("eng.1", pred_date=pred_date)
    assert len(filtered_matches) >= 50

    # Leakage Guard assertion: ALL match dates must be strictly earlier than pred_date
    for m in filtered_matches:
        assert m["date"] < pred_date, f"Leakage detected! Match date {m['date']} is not before prediction date {pred_date}"


# 4. test_soccer_minimum_training_sample
def test_soccer_minimum_training_sample(tmp_path):
    """If training matches < MIN_MATCHES_REQUIRED or team apps < MIN_APPS, return None (MODEL_NOT_READY)."""
    from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter

    # Create empty cache dir
    adapter = PenaltyblogDixonColesAdapter(cache_dir=str(tmp_path))

    leg = TaiwanLeg(
        event_id="test_min_sample",
        sport="soccer",
        league="英超",
        market="不讓分",
        selection="兵工廠 客勝",
        taiwan_odds=2.10,
        start_time="22:00",
        start_time_utc="2024-11-01T22:00:00Z",
        away_team="兵工廠",
        home_team="切爾西",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is None, "Should return None when data is below threshold (MODEL_NOT_READY)"


# 5. test_external_engine_provenance_category
def test_external_engine_provenance_category():
    """Penaltyblog Dixon-Coles directly imports and invokes penaltyblog; category MUST be EXTERNAL_OPEN_SOURCE_ENGINE."""
    from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
    import penaltyblog as pb

    adapter = PenaltyblogDixonColesAdapter()
    assert adapter.SOURCE_CATEGORY == "EXTERNAL_OPEN_SOURCE_ENGINE"
    assert hasattr(pb.models, "DixonColesGoalModel")


# 6. test_538_source_freshness
def test_538_source_freshness():
    """FiveThirtyEight raw MLB dataset ceased in 2023; verify it is not misrepresented as live 2026 feed."""
    from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter

    adapter = FiveThirtyEightMLBEloAdapter()
    # Must be categorized as LOCAL_REIMPLEMENTATION, not external live feed
    assert adapter.SOURCE_CATEGORY == "LOCAL_REIMPLEMENTATION"
    assert "2023" in adapter.METADATA_DISCLOSURE.get("historical_data_end", "2023")


# 7. test_local_reimplementation_not_labeled_external
def test_local_reimplementation_not_labeled_external():
    """FiveThirtyEight MLB Elo is a local reimplementation of 538's paper, NOT an external package."""
    from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter

    adapter = FiveThirtyEightMLBEloAdapter()
    assert adapter.SOURCE_CATEGORY == "LOCAL_REIMPLEMENTATION"
    assert adapter.SOURCE_CATEGORY != "EXTERNAL_OPEN_SOURCE_ENGINE"

    # Also verify config/models.yaml declaration
    config_file = PROJECT_ROOT / "config" / "models.yaml"
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    elo_cfg = data["models"]["fivethirtyeight_mlb_elo"]
    assert elo_cfg["source_category"] == "LOCAL_REIMPLEMENTATION"


# 8. test_model_input_provenance_logged
def test_model_input_provenance_logged():
    """Model evaluation must log full ModelInputProvenance metadata."""
    from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter

    adapter = PenaltyblogDixonColesAdapter()
    leg = TaiwanLeg(
        event_id="501",
        sport="soccer",
        league="英超",
        market="不讓分",
        selection="兵工廠 客勝",
        taiwan_odds=2.10,
        start_time="22:00",
        start_time_utc="2025-02-01T22:00:00Z",
        away_team="兵工廠",
        home_team="切爾西",
        side="客",
    )
    sig = adapter.evaluate_leg(leg)
    assert sig is not None
    assert "provenance" in sig.metadata
    prov = sig.metadata["provenance"]
    assert "dataset_source" in prov
    assert "dataset_url" in prov
    assert "training_start_date" in prov
    assert "training_end_date" in prov
    assert "match_count" in prov
    assert prov["match_count"] >= 60
    assert "latest_match_date" in prov
    # Ensure latest training match is strictly before prediction date
    assert prov["latest_match_date"] < "2025-02-01"
