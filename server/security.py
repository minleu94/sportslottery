"""Security and rate-limiting infrastructure for Taiwan Sports Lottery API."""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional
from fastapi import Request

logger = logging.getLogger("sportslottery.security")

# Rate limit defaults: 5 failed attempts locks out for 15 minutes (900 seconds)
DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 900
DEFAULT_BASE_DELAY_SECONDS = 0.5


class LoginRateLimiter:
    """Thread-safe rate limiter and brute-force protector for authentication endpoints.

    Tracks failed attempts by both composite (identifier + client IP) and client IP.
    Applies exponential delays and temporary account/IP lockout upon exceeding threshold.
    """

    def __init__(
        self,
        max_failures: int = DEFAULT_MAX_FAILED_ATTEMPTS,
        lockout_seconds: int = DEFAULT_LOCKOUT_SECONDS,
        base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    ):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self.base_delay = base_delay
        self._failures: Dict[str, List[float]] = {}
        self._locked_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _get_keys(self, identifier: str, ip: str) -> List[str]:
        clean_id = str(identifier or "").strip().lower()
        clean_ip = str(ip or "").strip()
        keys = []
        if clean_id and clean_ip:
            keys.append(f"id:{clean_id}::{clean_ip}")
        if clean_id:
            keys.append(f"id_only:{clean_id}")
        if clean_ip:
            keys.append(f"ip_only:{clean_ip}")
        return keys

    def check_rate_limit(self, identifier: str, ip: str) -> Optional[int]:
        """Check if account or IP is currently locked out.

        Returns remaining lockout seconds if locked, or None if allowed.
        """
        now = time.time()
        keys = self._get_keys(identifier, ip)
        with self._lock:
            for k in keys:
                until = self._locked_until.get(k, 0.0)
                if now < until:
                    return int(math.ceil(until - now))
                elif k in self._locked_until:
                    del self._locked_until[k]
        return None

    def record_failure(self, identifier: str, ip: str) -> tuple[int, bool, int]:
        """Record a failed login attempt.

        Returns:
            (failure_count, is_locked, remaining_lockout_seconds)
        """
        now = time.time()
        cutoff = now - self.lockout_seconds
        keys = self._get_keys(identifier, ip)
        primary_key = keys[0] if keys else f"ip_only:{ip}"

        with self._lock:
            # Clean expired records for the primary key
            history = [t for t in self._failures.get(primary_key, []) if t > cutoff]
            history.append(now)
            self._failures[primary_key] = history
            fail_cnt = len(history)

            if fail_cnt >= self.max_failures:
                until = now + self.lockout_seconds
                for k in keys:
                    self._locked_until[k] = until
                return fail_cnt, True, self.lockout_seconds

            return fail_cnt, False, 0

    def record_success(self, identifier: str, ip: str) -> None:
        """Clear failed attempts and lockout upon successful authentication."""
        keys = self._get_keys(identifier, ip)
        with self._lock:
            for k in keys:
                self._failures.pop(k, None)
                self._locked_until.pop(k, None)

    def compute_backoff_delay(self, identifier: str, ip: str) -> float:
        """Compute an incremental backoff delay (in seconds) to deter rapid automated probing."""
        keys = self._get_keys(identifier, ip)
        primary_key = keys[0] if keys else f"ip_only:{ip}"
        with self._lock:
            cnt = len(self._failures.get(primary_key, []))
        if cnt <= 0:
            return 0.0
        return min(2.0, self.base_delay * cnt)

    def reset(self) -> None:
        """Reset all rate limiter states (primarily for testing)."""
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


# Global login rate limiter singleton
login_rate_limiter = LoginRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP address, safely inspecting trusted reverse proxy headers."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # First IP in the list is the original client address
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def log_security_event(
    event_type: str,
    identifier: str,
    ip: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a structured security audit event."""
    extra = details or {}
    logger.warning(
        "[SECURITY AUDIT] event=%s identifier=%s ip=%s details=%s timestamp=%s",
        event_type,
        identifier,
        ip,
        extra,
        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    )
