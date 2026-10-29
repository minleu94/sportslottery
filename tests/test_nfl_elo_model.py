#!/usr/bin/env python3
"""Unit tests for NFL Elo Quantitative Valuation Engine."""

import pytest
from integrations.common.models import TaiwanLeg
from integrations.models.external.nfl_elo_model import NFLEloModel, _resolve_nfl_team_code


def test_nfl_team_code_resolution():
    assert _resolve_nfl_team_code("堪薩斯酋長") == "KC"
    assert _resolve_nfl_team_code("舊金山49人") == "SF"
    assert _resolve_nfl_team_code("水牛城比爾") == "BUF"
    assert _resolve_nfl_team_code("綠灣包裝工") == "GB"
    assert _resolve_nfl_team_code("Baltimore Ravens") == "BAL"


def test_nfl_elo_model_match_prediction():
    model = NFLEloModel()
    # KC (Home, 1660) vs CAR (Away, 1340)
    # Diff with HFA = 1660 - 1340 + 55 = +375 Elo
    pred = model.predict_match(home_team="堪薩斯酋長", away_team="卡羅萊納黑豹")
    assert pred["elo_home"] == 1660.0
    assert pred["elo_away"] == 1340.0
    assert pred["prob_home"] > 0.85
    assert pred["prob_away"] < 0.15
    assert pred["projected_margin"] > 10.0


def test_nfl_elo_model_evaluate_moneyline_leg():
    model = NFLEloModel()
    leg = TaiwanLeg(
        event_id="nfl_101",
        sport="football",
        league="NFL",
        away_team="底特律雄獅",
        home_team="堪薩斯酋長",
        market="不讓分",
        selection="主勝",
        side="主",
        taiwan_odds=1.55,
        odds_status="LIVE",
    )

    signal = model.evaluate_leg(leg)
    assert signal is not None
    assert signal.source_id == "nfl_elo_model"
    assert signal.market == "不讓分"
    assert signal.probability > 0.50
    assert "projected_margin" in signal.metadata


def test_nfl_elo_model_evaluate_spread_leg():
    model = NFLEloModel()
    leg = TaiwanLeg(
        event_id="nfl_102",
        sport="football",
        league="NFL",
        away_team="休士頓德州人",
        home_team="堪薩斯酋長",
        market="讓分",
        selection="主讓分",
        side="主",
        line="-3.5",
        taiwan_odds=1.75,
        odds_status="LIVE",
    )

    signal = model.evaluate_leg(leg)
    assert signal is not None
    assert 0.0 < signal.probability < 1.0


def test_nfl_elo_model_skips_non_nfl_games():
    model = NFLEloModel()
    leg = TaiwanLeg(
        event_id="mlb_101",
        sport="baseball",
        league="MLB",
        away_team="洋基",
        home_team="紅襪",
        market="不讓分",
        selection="主勝",
        side="主",
        taiwan_odds=1.85,
    )
    assert model.evaluate_leg(leg) is None
