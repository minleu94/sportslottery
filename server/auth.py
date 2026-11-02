"""Server-side session management and authentication/authorization dependencies for FastAPI.

Provides:
- Cryptographic session generation and TTL validation
- Token version verification and instantaneous cross-device revocation upon credential changes
- Hybrid authentication extracting tokens from HttpOnly Cookies, Authorization Bearer, or X-Session-Token
- RBAC and profile isolation guards
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from core.profile_manager import DEFAULT_PROFILE_ID
from core.storage_config import get_db_path

SESSION_TTL_SECONDS = 7 * 86400  # 7 days


class SessionManager:
    """Thread-safe sessions persisted in the shared application database."""

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._legacy_admin_sessions_revoked_for: set[str] = set()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            name TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            token_version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )""")
        db_key = str(db_path.resolve())
        with self._lock:
            if db_key not in self._legacy_admin_sessions_revoked_for:
                # Older releases derived admin privileges from the display name
                # "Archie". Revoke persisted non-default elevated sessions once
                # per database after upgrade.
                conn.execute(
                    "DELETE FROM auth_sessions WHERE profile_id != ? AND is_admin != 0",
                    (DEFAULT_PROFILE_ID,),
                )
                conn.commit()
                self._legacy_admin_sessions_revoked_for.add(db_key)
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_session(self, profile: Dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        pid = str(profile.get("id") or "").strip()
        pname = str(profile.get("name") or "").strip()
        token_version = int(profile.get("token_version") or 1)
        is_admin = pid == DEFAULT_PROFILE_ID

        must_change_password = False
        if is_admin:
            try:
                from core.profile_manager import ProfileManager
                pm = ProfileManager()
                must_change_password = pm.is_default_admin_pin()
            except Exception:
                pass

        session_data = {
            "token": token,
            "profile_id": pid,
            "name": pname,
            "is_admin": is_admin,
            "must_change_password": must_change_password,
            "token_version": token_version,
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        with self._lock:
            self._sessions[token] = session_data
        try:
            with self._connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO auth_sessions
                    (token_hash, profile_id, name, is_admin, token_version, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (self._token_hash(token), pid, pname, int(is_admin), token_version, now, now + self.ttl_seconds),
                )
        except sqlite3.Error:
            # Keep the session usable for this process if persistent storage is temporarily unavailable.
            pass
        return token

    def get_session(self, token: Optional[str], check_version: bool = True) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        token_str = str(token).strip()
        now = time.time()
        with self._lock:
            session = self._sessions.get(token_str)
            if not session:
                session = None
            if session and now > session.get("expires_at", 0):
                self._sessions.pop(token_str, None)
                session = None
            session_copy = dict(session) if session else None
        if session_copy is None:
            try:
                with self._connection() as conn:
                    row = conn.execute(
                        """SELECT profile_id, name, is_admin, token_version, created_at, expires_at
                        FROM auth_sessions WHERE token_hash = ?""",
                        (self._token_hash(token_str),),
                    ).fetchone()
                    if row:
                        if now > float(row[5]):
                            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (self._token_hash(token_str),))
                            return None
                        pid, name, is_admin, token_version, created_at, expires_at = row
                        session_copy = {
                            "token": token_str,
                            "profile_id": pid,
                            "name": name,
                            # The persisted flag is retained for schema compatibility,
                            # but authorization always comes from the fixed profile ID.
                            "is_admin": str(pid) == DEFAULT_PROFILE_ID,
                            "token_version": int(token_version),
                            "created_at": float(created_at),
                            "expires_at": float(expires_at),
                        }
                        with self._lock:
                            self._sessions[token_str] = dict(session_copy)
            except sqlite3.Error:
                return None
        if session_copy is None:
            return None

        # Old in-memory sessions may predate the role fix and still carry an
        # elevated flag. Invalidate them instead of merely demoting them.
        if str(session_copy.get("profile_id") or "").strip() != DEFAULT_PROFILE_ID and session_copy.get("is_admin"):
            self.revoke_session(token_str)
            return None

        # Never trust a serialized or cached role bit. This also protects callers
        # while profile storage is temporarily unavailable.
        session_copy["is_admin"] = str(session_copy.get("profile_id") or "").strip() == DEFAULT_PROFILE_ID

        # Enforce token version against database state if credential was changed
        if check_version and session_copy.get("profile_id"):
            try:
                from core.profile_manager import ProfileManager
                pm = ProfileManager()
                profile = pm.get_profile(session_copy["profile_id"])
                if not profile:
                    self.revoke_session(token_str)
                    return None
                session_copy["name"] = str(profile.get("name") or session_copy.get("name") or "")
                session_copy["is_admin"] = session_copy["profile_id"] == DEFAULT_PROFILE_ID
                current_ver = pm.get_token_version(session_copy["profile_id"])
                if session_copy.get("token_version", 1) < current_ver:
                    self.revoke_session(token_str)
                    return None
                if session_copy["is_admin"]:
                    # Fail closed for privileged actions if the admin credential
                    # state cannot be checked.
                    try:
                        session_copy["must_change_password"] = pm.is_default_admin_pin()
                    except Exception:
                        session_copy["must_change_password"] = True
                else:
                    session_copy["must_change_password"] = False
            except Exception:
                # Authentication and authorization must fail closed when profile
                # or token-version state cannot be read.
                return None

        return session_copy

    def revoke_session(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            token_str = str(token).strip()
            existed = bool(self._sessions.pop(token_str, None))
        try:
            with self._connection() as conn:
                cursor = conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (self._token_hash(token_str),))
                existed = existed or cursor.rowcount > 0
        except sqlite3.Error:
            pass
        return existed

    def revoke_all_for_profile(self, profile_id: str) -> int:
        """Revoke all active sessions belonging to a specific profile (e.g. after PIN change)."""
        pid = str(profile_id or "").strip()
        with self._lock:
            to_remove = [t for t, s in self._sessions.items() if s.get("profile_id") == pid]
            for t in to_remove:
                del self._sessions[t]
        try:
            with self._connection() as conn:
                cursor = conn.execute("DELETE FROM auth_sessions WHERE profile_id = ?", (pid,))
                return max(len(to_remove), cursor.rowcount)
        except sqlite3.Error:
            return len(to_remove)

    def clean_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [t for t, s in self._sessions.items() if now > s.get("expires_at", 0)]
            for t in expired:
                del self._sessions[t]
        try:
            with self._connection() as conn:
                cursor = conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
                return max(len(expired), cursor.rowcount)
        except sqlite3.Error:
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


def require_any_authenticated_session(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Dict[str, Any]:
    """Enforce that request provides a valid, unexpired, unrevoked session token (permits password change state)."""
    token = extract_token_from_request(request, authorization, x_session_token)
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="【未授權存取】請先完成身分登入以取得有效作業 Session。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


def require_authenticated_session(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Dict[str, Any]:
    """Enforce that request provides a valid session that has no pending password change requirements."""
    session = require_any_authenticated_session(request, authorization, x_session_token)
    if session.get("must_change_password"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="【安全限制】管理員使用預設密碼 0000，必須先變更為 8 位純數字密碼方可操作系統功能。",
        )
    return session


def verify_no_pending_password_change(
    session: Optional[Dict[str, Any]] = Depends(get_current_session_optional),
) -> Optional[Dict[str, Any]]:
    """Guard optional-auth endpoints (e.g. recommendation search) against locked default admin sessions."""
    if session and session.get("must_change_password"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="【安全限制】管理員使用預設密碼 0000，必須先變更為 8 位純數字密碼方可操作推薦功能。",
        )
    return session


def verify_profile_ownership(profile_id: str, session: Dict[str, Any]) -> None:
    """Ensure session owner matches requested profile_id, unless admin ('default')."""
    target_pid = str(profile_id or "").strip()
    sess_pid = str(session.get("profile_id") or "").strip()
    is_admin = sess_pid == DEFAULT_PROFILE_ID

    if not is_admin and sess_pid != target_pid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"【權限不足】您目前的登入身分（ID: {sess_pid}）無權操作玩家（ID: {target_pid}）的資金或注單。",
        )


def require_active_admin_session(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
) -> Dict[str, Any]:
    """Enforce that request provides a valid admin session that has completed initial 0000 password change."""
    session = require_any_authenticated_session(request, authorization, x_session_token)
    is_admin = str(session.get("profile_id") or "").strip() == DEFAULT_PROFILE_ID
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="【權限不足】僅系統管理者可執行此項管理操作。",
        )
    if session.get("must_change_password"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="【安全限制】管理員使用預設密碼 0000，必須先變更為 8 位純數字密碼方可操作管理功能。",
        )
    return session

