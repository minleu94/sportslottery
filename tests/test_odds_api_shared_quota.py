"""Deterministic tests for persistent Odds API caching and quota coordination."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from integrations.odds.the_odds_api import TheOddsApiClient


class _Response:
    headers = {
        "x-requests-used": "2",
        "x-requests-remaining": "498",
        "x-requests-last": "2",
    }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"[]"


def _client(tmp_path: Path, **kwargs) -> TheOddsApiClient:
    cfg = tmp_path / "odds.yaml"
    cfg.write_text("monthly_quota: 500\nregions: us,eu\nscheduled_markets: h2h\ncache_ttl_seconds: 900\n", encoding="utf-8")
    return TheOddsApiClient(
        config_path=cfg,
        local_config_path=tmp_path / "local.yaml",
        env_file_path=tmp_path / ".env",
        cache_path=tmp_path / "cache.json",
        api_key="unit-test-key",
        **kwargs,
    )


def test_two_clients_coalesce_query_and_share_credit_state(tmp_path: Path):
    first = _client(tmp_path)
    second = _client(tmp_path)
    started = threading.Event()
    calls = []

    def fake_urlopen(*_args, **_kwargs):
        calls.append(1)
        started.set()
        time.sleep(0.08)
        return _Response()

    with patch("integrations.odds.the_odds_api.urllib.request.urlopen", side_effect=fake_urlopen):
        barrier = threading.Barrier(2)
        errors = []

        def run(client):
            try:
                barrier.wait()
                client.fetch_market_odds("NBA", markets="h2h")
            except Exception as exc:  # pragma: no cover - assertion reports unexpected worker failure
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(client,)) for client in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert len(calls) == 1
    status = second.get_source_status()
    assert status["requests_used_this_month"] == 2
    assert status["official_remaining"] == 498
    assert status["request_metrics"]["api_requests"] == 1
    assert status["request_metrics"]["coalesced_requests"] == 1


def test_automated_request_obeys_450_ceiling_and_manual_reserve(tmp_path: Path):
    client = _client(tmp_path)
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    client._cache_data["usage"][month_key] = 449
    client._cache_data["requests_remaining_official"] = 51
    client._cache_data["requests_remaining_month_key"] = month_key
    client._save_cache()
    calls = []

    with patch("integrations.odds.the_odds_api.urllib.request.urlopen", side_effect=lambda *_a, **_k: calls.append(1)):
        result = client.fetch_market_odds("NBA", markets="h2h", automated=True)

    assert calls == []
    assert result and all(snapshot.is_synthetic for snapshot in result)
    status = client.get_source_status()
    assert status["requests_used_this_month"] == 449
    assert status["official_remaining"] == 51
    assert status["request_metrics"]["quota_skips"] == 1


def test_manual_query_can_use_reserved_credit_but_query_dimensions_do_not_alias(tmp_path: Path):
    client = _client(tmp_path)
    calls = []

    def fake_urlopen(*_args, **_kwargs):
        calls.append(1)
        return _Response()

    with patch("integrations.odds.the_odds_api.urllib.request.urlopen", side_effect=fake_urlopen):
        client.fetch_market_odds("NBA", markets="h2h", automated=False)
        client.fetch_market_odds("NBA", markets="totals", automated=False)

    assert len(calls) == 2
    entries = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))["entries"]
    assert len(entries) == 2


def test_failure_backoff_prevents_immediate_retry_and_records_metrics(tmp_path: Path):
    client = _client(tmp_path)
    calls = []

    def failing_urlopen(*_args, **_kwargs):
        calls.append(1)
        raise TimeoutError("mock timeout")

    with patch("integrations.odds.the_odds_api.urllib.request.urlopen", side_effect=failing_urlopen):
        client.fetch_market_odds("NBA", markets="h2h")
        client.fetch_market_odds("NBA", markets="h2h")

    assert len(calls) == 1
    status = client.get_source_status()
    assert status["request_metrics"]["request_failures"] == 1
    assert status["request_metrics"]["backoff_skips"] == 1
    assert status["retry_after_utc"]
