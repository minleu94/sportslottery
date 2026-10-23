#!/usr/bin/env python3
"""Unit tests for NBA Elo & Four Factors Quantitative Engine."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from integrations.common.models import TaiwanLeg, PredictionSignal
from integrations.models.external.nba_elo_engine import NBAEloEngine, _resolve_nba_team


def test_resolve_nba_team():
    # Chinese alias lookup
    bos = _resolve_nba_team("塞爾提克")
    assert bos is not None
    assert bos.canonical_id == "NBA_BOS"

    gsw = _resolve_nba_team("金州勇士")
    assert gsw is not None
    assert gsw.canonical_id == "NBA_GSW"

    den = _resolve_nba_team("金塊")
    assert den is not None
    assert den.canonical_id == "NBA_DEN"


def test_nba_elo_predict_match():
    engine = NBAEloEngine()
    pred = engine.predict_match(home_team="塞爾提克", away_team="湖人")
    assert pred["home_canonical"] == "NBA_BOS"
    assert pred["away_canonical"] == "NBA_LAL"
    assert pred["elo_home"] > 1600.0  # Boston is baseline 1660
    assert pred["elo_away"] > 1500.0  # Lakers baseline 1520
    # Home probability + Away probability = 1.0
    assert pytest.approx(pred["prob_home"] + pred["prob_away"], rel=1e-4) == 1.0
    # With HCA, Boston should have strong win probability
    assert pred["prob_home"] > 0.60
    assert pred["projected_margin"] > 0.0
    assert pred["projected_total"] > 200.0


def test_nba_elo_spread_probability():
    engine = NBAEloEngine()
    # Projected margin = +6.0 (home favored by 6)
    # Line = -3.5 (home gives 3.5 points) -> home covers if win by >= 4
    p_home_cover = engine.evaluate_spread_probability(projected_margin=6.0, line=-3.5, side="主")
    p_away_cover = engine.evaluate_spread_probability(projected_margin=6.0, line=-3.5, side="客")
    # Home covering spread should be > 50%
    assert p_home_cover > 0.50
    assert p_away_cover < 0.50


def test_nba_elo_totals_probability():
    engine = NBAEloEngine()
    # Projected total = 228.0, Line = 222.5
    p_over = engine.evaluate_totals_probability(projected_total=228.0, total_line=222.5, side="大")
    p_under = engine.evaluate_totals_probability(projected_total=228.0, total_line=222.5, side="小")
    assert p_over > 0.50
    assert p_under < 0.50


def test_nba_elo_evaluate_leg_moneyline():
    engine = NBAEloEngine()
    now = datetime.now(timezone.utc).isoformat()
    leg = TaiwanLeg(
        event_id="NBA_2026_01",
        sport="basketball",
        league="NBA",
        home_team="波士頓塞爾提克",
        away_team="丹佛金塊",
        market="不讓分",
        selection="波士頓塞爾提克",
        side="主",
        taiwan_odds=1.75,
        start_time_utc=now,
        odds_scraped_at=now,
        odds_status="LIVE",
    )
    sig = engine.evaluate_leg(leg)
    assert sig is not None
    assert isinstance(sig, PredictionSignal)
    assert sig.source_category == "OPEN_SOURCE_ENGINE"
    assert sig.independence_group == "NBA_ELO_ENGINE"
    assert sig.market == "不讓分"
    assert 0.0 < sig.probability < 1.0


def test_nba_elo_evaluate_leg_spread():
    engine = NBAEloEngine()
    now = datetime.now(timezone.utc).isoformat()
    leg = TaiwanLeg(
        event_id="NBA_2026_02",
        sport="basketball",
        league="NBA",
        home_team="塞爾提克",
        away_team="金塊",
        market="讓分",
        selection="塞爾提克 -4.5",
        side="主",
        line="-4.5",
        taiwan_odds=1.75,
        start_time_utc=now,
        odds_scraped_at=now,
        odds_status="LIVE",
    )
    sig = engine.evaluate_leg(leg)
    assert sig is not None
    assert sig.market == "讓分"
    assert 0.0 < sig.probability < 1.0


def test_nba_elo_evaluate_leg_totals():
    engine = NBAEloEngine()
    now = datetime.now(timezone.utc).isoformat()
    leg = TaiwanLeg(
        event_id="NBA_2026_03",
        sport="basketball",
        league="NBA",
        home_team="塞爾提克",
        away_team="金塊",
        market="大小",
        selection="大 225.5",
        side="大",
        line="225.5",
        taiwan_odds=1.75,
        start_time_utc=now,
        odds_scraped_at=now,
        odds_status="LIVE",
    )
    sig = engine.evaluate_leg(leg)
    assert sig is not None
    assert sig.market == "大小"
    assert 0.0 < sig.probability < 1.0


def test_nba_elo_ignores_other_sports():
    engine = NBAEloEngine()
    now = datetime.now(timezone.utc).isoformat()
    leg = TaiwanLeg(
        event_id="MLB_01",
        sport="baseball",
        league="MLB",
        home_team="紅襪",
        away_team="洋基",
        market="不讓分",
        selection="主",
        side="主",
        taiwan_odds=1.75,
        start_time_utc=now,
        odds_scraped_at=now,
        odds_status="LIVE",
    )
    assert engine.evaluate_leg(leg) is None


def test_nba_elo_state_persistence(tmp_path):
    state_file = tmp_path / "nba_elo_test.json"
    engine = NBAEloEngine(state_file=state_file)
    engine.elo_ratings["NBA_BOS"] = 1700.0
    engine.processed_games_count = 50
    engine.save_state()

    assert state_file.exists()

    engine2 = NBAEloEngine(state_file=state_file)
    assert engine2.elo_ratings["NBA_BOS"] == 1700.0
    assert engine2.processed_games_count == 50
