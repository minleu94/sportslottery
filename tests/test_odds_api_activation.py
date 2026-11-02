#!/usr/bin/env python3
"""Tests for The Odds API Activation, Key Resolution, and Quota Safety Guard."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from integrations.odds.the_odds_api import (
    TheOddsApiClient,
    _parse_env_file,
    save_local_api_key,
    SPORT_KEY_MAP,
)


def test_parse_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Comment line\n"
        "THE_ODDS_API_KEY=test_the_odds_key_123\n"
        "SOME_OTHER_KEY='hello_world'\n"
        "EMPTY_LINE=\n",
        encoding="utf-8",
    )
    parsed = _parse_env_file(env_file)
    assert parsed["THE_ODDS_API_KEY"] == "test_the_odds_key_123"
    assert parsed["SOME_OTHER_KEY"] == "hello_world"
    assert parsed["EMPTY_LINE"] == ""


def test_api_key_resolution_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base_cfg_path = tmp_path / "odds_api.yaml"
    local_cfg_path = tmp_path / "odds_api.local.yaml"
    env_path = tmp_path / ".env"
    cache_path = tmp_path / "cache.json"

    base_cfg_path.write_text("api_key: base_key\n", encoding="utf-8")
    local_cfg_path.write_text("api_key: local_key\n", encoding="utf-8")
    env_path.write_text("THE_ODDS_API_KEY=dotenv_key\n", encoding="utf-8")

    # Clear env
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    # 1. Explicit arg wins
    c1 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
        api_key="explicit_key",
    )
    assert c1.api_key == "explicit_key"
    assert c1.key_source == "EXPLICIT_ARG"

    # 2. THE_ODDS_API_KEY env var wins over dotenv / local / base
    monkeypatch.setenv("THE_ODDS_API_KEY", "env_the_odds_key")
    c2 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
    )
    assert c2.api_key == "env_the_odds_key"
    assert c2.key_source == "ENV_THE_ODDS_API_KEY"

    # 3. ODDS_API_KEY (backward compat)
    monkeypatch.delenv("THE_ODDS_API_KEY")
    monkeypatch.setenv("ODDS_API_KEY", "env_odds_key")
    c3 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
    )
    assert c3.api_key == "env_odds_key"
    assert c3.key_source == "ENV_ODDS_API_KEY"

    # 4. Dotenv in root
    monkeypatch.delenv("ODDS_API_KEY")
    c4 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
    )
    assert c4.api_key == "dotenv_key"
    assert c4.key_source == "DOTENV"

    # 5. Local config yaml (gitignored)
    env_path.write_text("", encoding="utf-8")
    c5 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
    )
    assert c5.api_key == "local_key"
    assert c5.key_source == "LOCAL_CONFIG"

    # 6. Base config yaml
    local_cfg_path.write_text("", encoding="utf-8")
    c6 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
    )
    assert c6.api_key == "base_key"
    assert c6.key_source == "BASE_CONFIG"

    # 7. Unconfigured
    base_cfg_path.write_text("", encoding="utf-8")
    c7 = TheOddsApiClient(
        config_path=base_cfg_path,
        local_config_path=local_cfg_path,
        env_file_path=env_path,
        cache_path=cache_path,
    )
    assert c7.api_key == ""
    assert c7.key_source == "UNCONFIGURED"
    status = c7.get_source_status()
    assert status["operating_mode"] in ("UNCONFIGURED", "SYNTHETIC_FIXTURE")
    assert status["has_api_key"] is False


def test_save_api_key_locally(tmp_path: Path):
    local_cfg = tmp_path / "odds_api.local.yaml"
    base_cfg = tmp_path / "odds_api.yaml"
    base_cfg.write_text("monthly_quota: 500\n", encoding="utf-8")

    client = TheOddsApiClient(
        config_path=base_cfg,
        local_config_path=local_cfg,
        env_file_path=tmp_path / ".env",
        cache_path=tmp_path / "cache.json",
    )
    assert client.api_key == ""

    # Save via helper
    ok = client.save_api_key("my_new_secret_key_999")
    assert ok is True
    assert client.api_key == "my_new_secret_key_999"
    assert client.key_source == "LOCAL_CONFIG"

    # Verify file content
    data = yaml.safe_load(local_cfg.read_text(encoding="utf-8"))
    assert data["api_key"] == "my_new_secret_key_999"


def test_quota_safety_pause_and_exhaustion(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    client = TheOddsApiClient(
        cache_path=cache_path,
        api_key="valid_test_key",
    )

    # 1. Normal state (Configured before first live fetch)
    status = client.get_source_status()
    assert status["operating_mode"] in ("KEY_CONFIGURED_UNVERIFIED", "LIVE_API")
    assert status["has_api_key"] is True

    # 2. Safety pause state: remaining <= 5
    client._cache_data["requests_remaining_official"] = 4
    status_paused = client.get_source_status()
    assert status_paused["operating_mode"] == "QUOTA_SAFETY_PAUSE"

    # When safety pause is triggered, fetch_market_odds safely serves synthetic
    snaps = client.fetch_market_odds("MLB")
    assert len(snaps) > 0
    assert all(s.is_synthetic for s in snaps)

    # 3. Quota exhausted: remaining <= 0
    client._cache_data["requests_remaining_official"] = 0
    status_exhausted = client.get_source_status()
    assert status_exhausted["operating_mode"] == "QUOTA_EXHAUSTED"


def test_sports_coverage_mapping():
    assert "MLB" in SPORT_KEY_MAP
    assert "NBA" in SPORT_KEY_MAP
    assert "NFL" in SPORT_KEY_MAP
    assert "EPL" in SPORT_KEY_MAP
    assert "LALIGA" in SPORT_KEY_MAP
    assert "CHAMPIONS_LEAGUE" in SPORT_KEY_MAP
    assert "BUNDESLIGA" in SPORT_KEY_MAP
    assert "SERIE_A" in SPORT_KEY_MAP
