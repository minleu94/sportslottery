#!/usr/bin/env python3
"""Unit tests for ParlayEngine line movement integration (Steam boost & Trap filtering)."""

from datetime import datetime, timedelta, timezone
import pytest
from core.parlay_engine import ParlayEngine
from integrations.common.models import TaiwanLeg


def make_leg(event_id, selection, odds, is_steam=False, is_trap=False):
    now = datetime.now(timezone.utc)
    return TaiwanLeg(
        event_id=event_id,
        sport="baseball",
        league="MLB",
        away_team=f"Away_{event_id}",
        home_team=f"Home_{event_id}",
        market="不讓分",
        selection=selection,
        side="主",
        taiwan_odds=odds,
        odds_status="FRESH",
        start_time_utc=(now + timedelta(hours=3)).isoformat(),
        odds_scraped_at=(now - timedelta(minutes=1)).isoformat(),
        evidence_quality="HIGH",
        signal_evidence={
            "market_complete": True,
            "evidence_quality": "HIGH",
            "non_market_supports": 2,
            "line_movement": {
                "is_steam": is_steam,
                "is_trap_warning": is_trap,
                "delta_odds": -0.15 if is_steam else (+0.15 if is_trap else 0.0),
            },
        },
    )


def test_parlay_exclude_traps_filters_trap_combinations():
    engine = ParlayEngine()
    leg1 = make_leg("E1", "主勝", 2.0, is_steam=True)
    leg2 = make_leg("E2", "主勝", 2.0, is_trap=True)  # Trap
    leg3 = make_leg("E3", "主勝", 2.0, is_steam=False)

    # Search with exclude_traps=True
    res_filtered = engine.search_parlays(
        legs=[leg1, leg2, leg3],
        min_odds=3.0,
        max_odds=10.0,
        min_legs=2,
        max_legs=2,
        exclude_traps=True,
    )

    # Any candidate with leg2 must be rejected!
    found_any = False
    for tier, combos in res_filtered.items():
        for combo in combos:
            found_any = True
            assert all(not l.get("signal_evidence", {}).get("line_movement", {}).get("is_trap_warning") for l in combo["legs"])
            assert combo["trap_count"] == 0

    assert found_any, "Should have found valid combo between leg1 and leg3"

    # Search without exclude_traps
    res_unfiltered = engine.search_parlays(
        legs=[leg1, leg2, leg3],
        min_odds=3.0,
        max_odds=10.0,
        min_legs=2,
        max_legs=2,
        exclude_traps=False,
    )
    # The combo with steam leg should rank higher than trap leg
    all_combos = []
    for tier, combos in res_unfiltered.items():
        all_combos.extend(combos)
    if all_combos:
        # Combo with steam should have has_steam=True
        assert any(c["has_steam"] for c in all_combos)
