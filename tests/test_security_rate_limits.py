from starlette.requests import Request

from server.security import LoginRateLimiter, RegistrationRateLimiter, get_client_ip


def _request(peer: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/profiles/login",
        "raw_path": b"/api/profiles/login",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 12345),
        "server": ("localhost", 8000),
    })


def test_login_limit_aggregates_identifiers_without_cross_ip_account_lockout():
    limiter = LoginRateLimiter(max_failures=2, max_ip_failures=3, lockout_seconds=60)
    assert limiter.record_failure("player-id", "198.51.100.10")[1] is False
    assert limiter.record_failure("player-name", "198.51.100.10")[1] is False
    _, locked, _ = limiter.record_failure("another-name", "198.51.100.10")
    assert locked is True
    assert limiter.check_rate_limit("unrelated", "198.51.100.10") is not None
    assert limiter.check_rate_limit("player-id", "198.51.100.11") is None


def test_login_limit_locks_only_the_same_account_and_source_pair():
    limiter = LoginRateLimiter(max_failures=2, max_ip_failures=10, lockout_seconds=60)
    limiter.record_failure("player-id", "198.51.100.10")
    _, locked, _ = limiter.record_failure("player-id", "198.51.100.10")
    assert locked is True
    assert limiter.check_rate_limit("player-id", "198.51.100.10") is not None
    assert limiter.check_rate_limit("player-id", "198.51.100.11") is None


def test_login_limit_blocks_distributed_guesses_for_one_account():
    limiter = LoginRateLimiter(
        max_failures=3,
        max_account_failures=4,
        max_ip_failures=20,
        lockout_seconds=60,
    )
    for address in ("198.51.100.10", "198.51.100.11", "198.51.100.12"):
        _, locked, _ = limiter.record_failure("player-id", address)
        assert locked is False

    _, locked, _ = limiter.record_failure("player-id", "198.51.100.13")
    assert locked is True
    assert limiter.check_rate_limit("player-id", "198.51.100.99") is not None


def test_forwarded_ip_is_ignored_from_untrusted_peer_and_walked_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "127.0.0.1/32")
    forwarded = [(b"x-forwarded-for", b"203.0.113.99, 198.51.100.22")]
    assert get_client_ip(_request("198.51.100.1", forwarded)) == "198.51.100.1"
    assert get_client_ip(_request("127.0.0.1", forwarded)) == "198.51.100.22"


def test_untrusted_real_ip_fallback_is_ignored(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "127.0.0.1/32")
    request = _request("127.0.0.1", [(b"x-real-ip", b"198.51.100.99")])
    assert get_client_ip(request) == "127.0.0.1"


def test_registration_limiter_window_and_bound():
    limiter = RegistrationRateLimiter(max_requests=2, window_seconds=10, max_entries=2)
    assert limiter.check_and_record("198.51.100.1") == (True, 0)
    assert limiter.check_and_record("198.51.100.1") == (True, 0)
    allowed, retry_after = limiter.check_and_record("198.51.100.1")
    assert allowed is False
    assert retry_after > 0

    assert limiter.check_and_record("198.51.100.2")[0] is True
    assert limiter.check_and_record("198.51.100.3")[0] is True
    assert len(limiter._events) <= 2
