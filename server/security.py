"""Security and rate-limiting infrastructure for Taiwan Sports Lottery API."""

from __future__ import annotations

import ipaddress
import logging
import math
import os
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import Request

logger = logging.getLogger("sportslottery.security")

DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 900
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_IP_FAILURES = 25
DEFAULT_MAX_ACCOUNT_FAILURES = 25
MAX_RATE_LIMIT_KEYS = 10000


def _trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    """Load configured trusted proxy addresses; loopback supports the local tunnel process."""
    configured = os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1,::1")
    networks = []
    for value in configured.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_IPS entry")
    return tuple(networks)


def _is_trusted_proxy(address: str, networks: tuple[ipaddress._BaseNetwork, ...]) -> bool:
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(candidate in network for network in networks)


class LoginRateLimiter:
    """Bounded sliding-window limits by account, account/source pair, and source IP.

    The account/source bucket provides a quick lock for repeated guesses from one
    address. The account-wide bucket closes distributed guessing across addresses,
    while the aggregate source bucket limits attempts spread across identifiers.
    """

    def __init__(
        self,
        max_failures: int = DEFAULT_MAX_FAILED_ATTEMPTS,
        lockout_seconds: int = DEFAULT_LOCKOUT_SECONDS,
        base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
        max_ip_failures: int = DEFAULT_MAX_IP_FAILURES,
        max_account_failures: int = DEFAULT_MAX_ACCOUNT_FAILURES,
        max_entries: int = MAX_RATE_LIMIT_KEYS,
    ):
        self.max_failures = max_failures
        self.max_ip_failures = max_ip_failures
        self.max_account_failures = max_account_failures
        self.lockout_seconds = lockout_seconds
        self.base_delay = base_delay
        self.max_entries = max_entries
        self._failures: Dict[str, List[float]] = {}
        self._locked_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _get_keys(self, identifier: str, ip: str) -> List[str]:
        clean_id = str(identifier or "").strip().lower()[:256]
        clean_ip = str(ip or "").strip()[:128]
        keys = []
        if clean_id and clean_ip:
            keys.append(f"id:{clean_id}::{clean_ip}")
        if clean_id:
            keys.append(f"account:{clean_id}")
        if clean_ip:
            keys.append(f"ip_only:{clean_ip}")
        return keys

    def _prune(self, now: float) -> None:
        cutoff = now - self.lockout_seconds
        for key, history in list(self._failures.items()):
            live = [stamp for stamp in history if stamp > cutoff]
            if live:
                self._failures[key] = live
            else:
                self._failures.pop(key, None)
        for key, until in list(self._locked_until.items()):
            if until <= now:
                self._locked_until.pop(key, None)
        excess = len(self._failures) - self.max_entries
        if excess > 0:
            oldest = sorted(
                self._failures,
                key=lambda key: self._failures[key][-1] if self._failures[key] else 0.0,
            )[:excess]
            for key in oldest:
                self._failures.pop(key, None)
                self._locked_until.pop(key, None)

    def check_rate_limit(self, identifier: str, ip: str) -> Optional[int]:
        """Return remaining lockout seconds, or None when the attempt is allowed."""
        now = time.time()
        keys = self._get_keys(identifier, ip)
        with self._lock:
            self._prune(now)
            remaining = [self._locked_until[key] - now for key in keys if self._locked_until.get(key, 0.0) > now]
            if remaining:
                return int(math.ceil(max(remaining)))
        return None

    def record_failure(self, identifier: str, ip: str) -> tuple[int, bool, int]:
        """Record one failed attempt and return (account_count, locked, seconds)."""
        now = time.time()
        cutoff = now - self.lockout_seconds
        keys = self._get_keys(identifier, ip)
        pair_key = next((key for key in keys if key.startswith("id:")), None)
        account_key = next((key for key in keys if key.startswith("account:")), None)
        ip_key = next((key for key in keys if key.startswith("ip_only:")), None)

        with self._lock:
            self._prune(now)
            thresholds = (
                (pair_key, self.max_failures),
                (account_key, self.max_account_failures),
                (ip_key, self.max_ip_failures),
            )
            counts: Dict[str, int] = {}
            locked_keys = set()
            until = now + self.lockout_seconds
            for key, threshold in thresholds:
                if key is None:
                    continue
                history = [stamp for stamp in self._failures.get(key, []) if stamp > cutoff]
                history.append(now)
                self._failures[key] = history
                counts[key] = len(history)
                if len(history) >= threshold:
                    self._locked_until[key] = until
                    locked_keys.add(key)

            if locked_keys:
                # Prefer the account-wide count in the response when a distributed
                # attempt reached that threshold; otherwise report the tightest key.
                report_key = (
                    account_key if account_key in locked_keys
                    else pair_key if pair_key in locked_keys
                    else ip_key
                )
                failure_count = counts.get(report_key or "", 0)
                return failure_count, True, self.lockout_seconds
            report_key = pair_key or account_key or ip_key
            return counts.get(report_key or "", 0), False, 0

    def record_success(self, identifier: str, ip: str) -> None:
        """Clear only the matching account/source bucket, preserving shared IP history."""
        keys = self._get_keys(identifier, ip)
        if not keys:
            return
        clear_keys = [key for key in keys if key.startswith(("id:", "account:"))]
        with self._lock:
            for key in clear_keys:
                self._failures.pop(key, None)
                self._locked_until.pop(key, None)

    def compute_backoff_delay(self, identifier: str, ip: str) -> float:
        """Compute the optional delay for an account/source attempt bucket."""
        keys = self._get_keys(identifier, ip)
        account_key = keys[0] if keys else "ip_only:unknown"
        with self._lock:
            cnt = len(self._failures.get(account_key, []))
        if cnt <= 0:
            return 0.0
        return min(2.0, self.base_delay * cnt)

    def reset(self) -> None:
        """Reset all limiter state (primarily for isolated tests)."""
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


class RegistrationRateLimiter:
    """Bounded successful-and-failed registration request limit per source."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 3600, max_entries: int = MAX_RATE_LIMIT_KEYS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._events: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(self, key: str) -> tuple[bool, int]:
        now = time.time()
        cutoff = now - self.window_seconds
        clean_key = str(key or "unknown")[:128]
        with self._lock:
            for old_key, history in list(self._events.items()):
                live = [stamp for stamp in history if stamp > cutoff]
                if live:
                    self._events[old_key] = live
                else:
                    self._events.pop(old_key, None)
            history = self._events.setdefault(clean_key, [])
            if len(history) >= self.max_requests:
                return False, max(1, int(math.ceil(history[0] + self.window_seconds - now)))
            history.append(now)
            if len(self._events) > self.max_entries:
                oldest_key = min(self._events, key=lambda item: self._events[item][-1])
                if oldest_key != clean_key:
                    self._events.pop(oldest_key, None)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


login_rate_limiter = LoginRateLimiter()
registration_rate_limiter = RegistrationRateLimiter()


def get_client_ip(request: Request) -> str:
    """Use proxy forwarding headers only when the socket peer is trusted."""
    peer = request.client.host if request.client and request.client.host else "127.0.0.1"
    networks = _trusted_proxy_networks()
    if not _is_trusted_proxy(peer, networks):
        return peer

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    chain = []
    for raw_ip in forwarded_for.split(","):
        raw_ip = raw_ip.strip()
        try:
            chain.append(str(ipaddress.ip_address(raw_ip)))
        except ValueError:
            continue
    # Walk from the proxy-facing end and select the first non-proxy hop. This
    # avoids trusting an attacker-supplied leftmost value when proxies append.
    for candidate in reversed(chain):
        if not _is_trusted_proxy(candidate, networks):
            return candidate

    # X-Real-IP is not a standardized chain and may preserve a client-supplied
    # value. Only accept the configured proxy chain; otherwise use the socket peer.
    return peer


def log_security_event(
    event_type: str,
    identifier: str,
    ip: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a structured security audit event."""
    logger.warning(
        "[SECURITY AUDIT] event=%s identifier=%s ip=%s details=%s timestamp=%s",
        event_type,
        identifier,
        ip,
        details or {},
        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    )
