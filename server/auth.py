"""Server-side session management and authentication/authorization dependencies for FastAPI.

Provides:
- Cryptographic session generation and TTL validation
- Token version verification and instantaneous cross-device revocation upon credential changes
- Hybrid authentication extracting tokens from HttpOnly Cookies, Authorization Bearer, or X-Session-Token
- RBAC and profile isolation guards
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request, status

SESSION_TTL_SECONDS = 7 * 86400  # 7 days


class SessionManager:
    """Thread-safe in-memory session manager with cryptographic token generation and revocation."""

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(self, profile: Dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        pid = str(profile.get("id") or "").strip()
        pname = str(profile.get("name") or "").strip()
        token_version = int(profile.get("token_version") or 1)
        session_data = {
            "token": token,
            "profile_id": pid,
            "name": pname,
            "is_admin": (pid == "default") or bool(profile.get("is_admin")),
            "token_version": token_version,
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        with self._lock:
            self._sessions[token] = session_data
        return token

    def get_session(self, token: Optional[str], check_version: bool = True) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        token_str = str(token).strip()
        now = time.time()
        with self._lock:
            session = self._sessions.get(token_str)
            if not session:
                return None
            if now > session.get("expires_at", 0):
                self._sessions.pop(token_str, None)
                return None
            session_copy = dict(session)

        # Enforce token version against database state if credential was changed
        if check_version and session_copy.get("profile_id"):
            try:
                from core.profile_manager import ProfileManager
                pm = ProfileManager()
                current_ver = pm.get_token_version(session_copy["profile_id"])
                if session_copy.get("token_version", 1) < current_ver:
                    self.revoke_session(token_str)
                    return None
            except Exception:
                pass

        return session_copy

    def revoke_session(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            return bool(self._sessions.pop(str(token).strip(), None))

    def revoke_all_for_profile(self, profile_id: str) -> int:
        """Revoke all active sessions belonging to a specific profile (e.g. after PIN change)."""
        pid = str(profile_id or "").strip()
        with self._lock:
            to_remove = [t for t, s in self._sessions.items() if s.get("profile_id") == pid]
            for t in to_remove:
                del self._sessions[t]
            return len(to_remove)

    def clean_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [t for t, s in self._sessions.items() if now > s.get("expires_at", 0)]
            for t in expired:
                del self._sessions[t]
            return len(expired)


# Singleton session manager
session_manager = SessionManager()


def extract_token_from_request(
    request: Optional[Request] = None,
    authorization: Optional[str] = None,
    x_session_token: Optional[str] = None,
) -> Optional[str]:
    """Extract raw session token from Bearer header, X-Session-Token, or HttpOnly Cookie."""
    # 1. Authorization: Bearer <token>
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        elif len(parts) == 1:
            return parts[0].strip()

    # 2. X-Session-Token header
    if x_session_token:
        return x_session_token.strip()

    # 3. HttpOnly Cookie: auth_session_token
    if request and hasattr(request, "cookies"):
        cookie_token = request.cookies.get("auth_session_token")
        if cookie_token:
            return cookie_token.strip()

    return None


def extract_token_from_header(
    authorization: Optional[str] = None,
    x_session_token: Optional[str] = None,
) -> Optional[str]:
    """Backward-compatible header extractor."""
    return extract_token_from_request(None, authorization, x_session_token)


def get_current_session_optional(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Optional[Dict[str, Any]]:
    """Optional session resolution (does not throw 401 if missing). Supports Cookie and Header."""
    token = extract_token_from_request(request, authorization, x_session_token)
    return session_manager.get_session(token)


def require_authenticated_session(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Dict[str, Any]:
    """Enforce that request provides a valid, unexpired, unrevoked session token."""
    token = extract_token_from_request(request, authorization, x_session_token)
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="【未授權存取】請先完成身分登入以取得有效作業 Session。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


def verify_profile_ownership(profile_id: str, session: Dict[str, Any]) -> None:
    """Ensure session owner matches requested profile_id, unless admin ('default')."""
    target_pid = str(profile_id or "").strip()
    sess_pid = str(session.get("profile_id") or "").strip()
    is_admin = session.get("is_admin", False) or (sess_pid == "default")

    if not is_admin and sess_pid != target_pid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"【權限不足】您目前的登入身分（ID: {sess_pid}）無權操作玩家（ID: {target_pid}）的資金或注單。",
        )
