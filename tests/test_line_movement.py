#!/usr/bin/env python3
"""Unit tests for LineMovementTracker (賠率變動與跳水/誘盤監控)."""

import json
from pathlib import Path
import pytest

from core.line_movement import LineMovementTracker
from integrations.common.models import TaiwanLeg


def test_line_movement_no_history(tmp_path: Path):
    empty_history = tmp_path / "odds_history.jsonl"
    tracker = LineMovementTracker(history_path=empty_history)

    leg = TaiwanLeg(
        event_id="TEST_001",
        canonical_event_id="MLB_20261024_LAD_NYY",
        sport="baseball",
        league="MLB",
        home_team="NYY",
        away_team="LAD",
        start_time="2026-10-24 10:00",
        market="SU",
        selection="客 (LAD)",
        taiwan_odds=1.75,
    )

    res = tracker.analyze_leg_movement(leg)
    assert res["movement_type"] == "NO_HISTORY"
    assert res["is_steam"] is False
    assert res["is_trap_warning"] is False
    assert "盤口初見" in res["badge_html"]
    assert res["current_odds"] == 1.75


def test_line_movement_steam_drop(tmp_path: Path):
    history_file = tmp_path / "odds_history.jsonl"
    records = [
        {
            "canonical_event_id": "MLB_20261024_LAD_NYY",
            "event_id": "TEST_001",
            "market": "SU",
            "selection": "客 (LAD)",
            "odds": 1.95,
            "observed_at": "2026-10-24T00:00:00Z",
        },
        {
            "canonical_event_id": "MLB_20261024_LAD_NYY",
            "event_id": "TEST_001",
            "market": "SU",
            "selection": "客 (LAD)",
            "odds": 1.82,
            "observed_at": "2026-10-24T02:00:00Z",
        },
        {
            "canonical_event_id": "MLB_20261024_LAD_NYY",
            "event_id": "TEST_001",
            "market": "SU",
            "selection": "客 (LAD)",
            "odds": 1.70,
            "observed_at": "2026-10-24T04:00:00Z",
        },
    ]
    with open(history_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    tracker = LineMovementTracker(history_path=history_file)

    leg = TaiwanLeg(
        event_id="TEST_001",
        canonical_event_id="MLB_20261024_LAD_NYY",
        sport="baseball",
        league="MLB",
        home_team="NYY",
        away_team="LAD",
        start_time="2026-10-24 10:00",
        market="SU",
        selection="客 (LAD)",
        taiwan_odds=1.70,
    )

    res = tracker.analyze_leg_movement(leg)
    assert res["movement_type"] == "STEAM_DROP"
    assert res["is_steam"] is True
    assert res["is_trap_warning"] is False
    assert res["open_odds"] == 1.95
    assert res["current_odds"] == 1.70
    assert res["delta_odds"] == -0.25
    assert "賠率跳水" in res["badge_html"]
    assert res["implied_prob_delta_pp"] > 0


def test_line_movement_reverse_drift_trap(tmp_path: Path):
    history_file = tmp_path / "odds_history.jsonl"
    records = [
        {
            "canonical_event_id": "NBA_20261024_BOS_MIA",
            "event_id": "TEST_002",
            "market": "SU",
            "selection": "客 (BOS)",
            "odds": 1.45,
            "observed_at": "2026-10-24T01:00:00Z",
        },
        {
            "canonical_event_id": "NBA_20261024_BOS_MIA",
            "event_id": "TEST_002",
            "market": "SU",
            "selection": "客 (BOS)",
            "odds": 1.62,
            "observed_at": "2026-10-24T03:00:00Z",
        },
    ]
    with open(history_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    tracker = LineMovementTracker(history_path=history_file)

    leg = TaiwanLeg(
        event_id="TEST_002",
        canonical_event_id="NBA_20261024_BOS_MIA",
        sport="basketball",
        league="NBA",
        home_team="MIA",
        away_team="BOS",
        start_time="2026-10-24 10:00",
        market="SU",
        selection="客 (BOS)",
        taiwan_odds=1.62,
    )

    res = tracker.analyze_leg_movement(leg)
    assert res["movement_type"] == "REVERSE_DRIFT"
    assert res["is_trap_warning"] is True
    assert res["is_steam"] is False
    assert res["open_odds"] == 1.45
    assert res["current_odds"] == 1.62
    assert res["delta_odds"] == 0.17
    assert "逆向升水" in res["badge_html"]


def test_line_movement_crowd_reverse_trap(tmp_path: Path):
    # Public heavily backs BOS (75%), but bookmaker drifts odds up by 0.06
    history_file = tmp_path / "odds_history.jsonl"
    records = [
        {
            "canonical_event_id": "NBA_20261024_BOS_MIA",
            "event_id": "TEST_003",
            "market": "SU",
            "selection": "客 (BOS)",
            "odds": 1.50,
            "observed_at": "2026-10-24T01:00:00Z",
        },
    ]
    with open(history_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    tracker = LineMovementTracker(history_path=history_file)

    leg = TaiwanLeg(
        event_id="TEST_003",
        canonical_event_id="NBA_20261024_BOS_MIA",
        sport="basketball",
        league="NBA",
        home_team="MIA",
        away_team="BOS",
        start_time="2026-10-24 10:00",
        market="SU",
        selection="客 (BOS)",
        taiwan_odds=1.56,
        signal_evidence={"consensus_ratio": 0.75},
    )

    res = tracker.analyze_leg_movement(leg)
    assert res["movement_type"] == "REVERSE_DRIFT"
    assert res["is_trap_warning"] is True
    assert "大眾熱投但莊家逆向給甜頭" in res["summary"]


def test_line_movement_stable(tmp_path: Path):
    history_file = tmp_path / "odds_history.jsonl"
    records = [
        {
            "canonical_event_id": "TEST_STABLE",
            "event_id": "TEST_004",
            "market": "SU",
            "selection": "主",
            "odds": 1.75,
            "observed_at": "2026-10-24T01:00:00Z",
        },
    ]
    with open(history_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    tracker = LineMovementTracker(history_path=history_file)

    leg = TaiwanLeg(
        event_id="TEST_004",
        canonical_event_id="TEST_STABLE",
        sport="baseball",
        league="CPBL",
        home_team="A",
        away_team="B",
        start_time="2026-10-24 17:00",
        market="SU",
        selection="主",
        taiwan_odds=1.76,
    )

    res = tracker.analyze_leg_movement(leg)
    assert res["movement_type"] == "STABLE"
    assert res["is_steam"] is False
    assert res["is_trap_warning"] is False
    assert "賠率平穩" in res["badge_html"]
