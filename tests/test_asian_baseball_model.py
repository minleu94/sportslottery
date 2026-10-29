#!/usr/bin/env python3
"""Unit tests for Asian Baseball Quantitative Valuation Engine (CPBL, NPB, KBO)."""

import pytest
from integrations.common.models import TaiwanLeg
from integrations.models.external.asian_baseball_model import AsianBaseballModel


def test_asian_baseball_model_predict_cpbl():
    model = AsianBaseballModel()
    pred = model.predict_match(league="CPBL", home_team="統一7-ELEVEn獅", away_team="富邦悍將")
    assert pred["norm_league"] == "CPBL"
    assert pred["elo_home"] > pred["elo_away"]
    assert pred["prob_home"] > 0.55
    assert pred["prob_away"] < 0.45


def test_asian_baseball_model_predict_npb():
    model = AsianBaseballModel()
    pred = model.predict_match(league="NPB", home_team="福岡軟銀鷹", away_team="中日龍")
    assert pred["norm_league"] == "NPB"
    assert pred["elo_home"] > 1550.0
    assert pred["prob_home"] > 0.60
    assert pred["projected_total"] < 8.0  # NPB is pitcher friendly


def test_asian_baseball_model_evaluate_cpbl_leg():
    model = AsianBaseballModel()
    leg = TaiwanLeg(
        event_id="cpbl_201",
        sport="baseball",
        league="CPBL (中職)",
        away_team="富邦悍將",
        home_team="統一獅",
        market="不讓分",
        selection="主勝",
        side="主",
        taiwan_odds=1.65,
        odds_status="LIVE",
    )

    signal = model.evaluate_leg(leg)
    assert signal is not None
    assert signal.source_id == "asian_baseball_model"
    assert signal.probability > 0.50
    assert "projected_margin" in signal.metadata


def test_asian_baseball_model_skips_mlb():
    model = AsianBaseballModel()
    leg = TaiwanLeg(
        event_id="mlb_201",
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
