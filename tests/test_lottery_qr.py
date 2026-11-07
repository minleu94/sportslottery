#!/usr/bin/env python3
"""Unit tests for Taiwan Sports Lottery QR Code generator."""

import pytest
from core.lottery_qr import (
    OFFICIAL_TAIWAN_LOTTERY_QR_SUPPORTED,
    build_lottery_slip_payload,
    generate_qr_code_data_url,
)


def test_build_lottery_slip_payload():
    legs = [
        {"event_id": "101", "league": "MLB", "away_team": "洋基", "home_team": "紅襪", "market": "不讓分", "selection": "洋基勝", "odds": 1.85},
        {"event_id": "202", "league": "NBA", "away_team": "湖人", "home_team": "勇士", "market": "讓分", "selection": "湖人 +4.5", "odds": 1.75},
    ]

    payload = build_lottery_slip_payload(legs, total_stake=100.0, parlay_name="2 串 1")
    assert payload["format"] == "SPORTSLOTTERY_LOCAL_EXPERIMENTAL"
    assert payload["total_stake"] == 100.0
    assert payload["ticket_type"] == "2P1"
    assert len(payload["legs"]) == 2
    assert payload["compact_code"].startswith("SPORTSLOTTERY_LOCAL|100|2P1|")
    assert OFFICIAL_TAIWAN_LOTTERY_QR_SUPPORTED is False


def test_generate_qr_code_data_url():
    data_url = generate_qr_code_data_url("SPORTSLOTTERY_LOCAL|100|2P1|TEST")
    assert data_url.startswith("data:image/png;base64,")
    assert len(data_url) > 100
