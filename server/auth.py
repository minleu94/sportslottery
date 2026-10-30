"""Server-side session management and authentication/authorization dependencies for FastAPI."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, status

SESSION_TTL_SECONDS = 7 * 86400  # 7 days


class SessionManager:
    """Thread-safe in-memory session manager with cryptographic token generation."""

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(self, profile: Dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        pid = str(profile.get("id") or "").strip()
        pname = str(profile.get("name") or "").strip()
        session_data = {
            "token": token,
            "profile_id": pid,
            "name": pname,
            "is_admin": (pid == "default"),
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        with self._lock:
            self._sessions[token] = session_data
        return token

    def get_session(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
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
            return dict(session)

    def revoke_session(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            return bool(self._sessions.pop(str(token).strip(), None))

    def clean_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [t for t, s in self._sessions.items() if now > s.get("expires_at", 0)]
            for t in expired:
                del self._sessions[t]
            return len(expired)


# Singleton session manager
session_manager = SessionManager()


def extract_token_from_header(
    authorization: Optional[str] = None,
    x_session_token: Optional[str] = None,
) -> Optional[str]:
    """Extract raw token string from Authorization header or X-Session-Token header."""
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        elif len(parts) == 1:
            return parts[0].strip()
    if x_session_token:
        return x_session_token.strip()
    return None


def get_current_session_optional(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Optional[Dict[str, Any]]:
    """Optional session resolution (does not throw 401 if missing)."""
    token = extract_token_from_header(authorization, x_session_token)
    return session_manager.get_session(token)


def require_authenticated_session(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Dict[str, Any]:
    """Enforce that request provides a valid, unexpired session token."""
    token = extract_token_from_header(authorization, x_session_token)
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
