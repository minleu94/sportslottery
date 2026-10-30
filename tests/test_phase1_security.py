#!/usr/bin/env python3
"""Comprehensive test suite for Phase 1 Security Hardening:
1. Mandatory LINE Webhook signature verification
2. Default admin weak PIN detection & strong passphrase support
3. Anti-brute-force rate limiting & temporary lockout on login and PIN endpoints
4. Profile exposure boundaries (minimal public profile info)
5. System storage status access control & path masking
6. Session lifecycle, HttpOnly cookie support, and instant cross-device revocation
7. Converged CORS policy without wildcard credentials
"""

import base64
import hashlib
import hmac
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from server.api import app, _line_notifier
from server.auth import session_manager
from server.security import login_rate_limiter
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID


@pytest.fixture(autouse=True)
def reset_security_state():
    """Ensure rate limiter and session states are cleanly reset between tests."""
    login_rate_limiter.reset()
    yield
    login_rate_limiter.reset()


# =====================================================================
# 1. Mandatory LINE Webhook Signature Verification
# =====================================================================

def test_line_webhook_production_missing_secret_rejects_503(monkeypatch):
    """In production mode without channel_secret, unsigned webhook callbacks must be rejected with 503."""
    monkeypatch.delenv("ALLOW_INSECURE_LINE_WEBHOOK", raising=False)
    orig_secret = _line_notifier.config.pop("channel_secret", None)
    client = TestClient(app)
    try:
        res = client.post("/callback", json={"events": []})
        assert res.status_code == 503
        assert "channel_secret is not configured" in res.json()["detail"]
    finally:
        if orig_secret is not None:
            _line_notifier.config["channel_secret"] = orig_secret


def test_line_webhook_production_signature_enforcement(monkeypatch):
    """When channel_secret is configured, callbacks must verify X-Line-Signature HMAC."""
    monkeypatch.delenv("ALLOW_INSECURE_LINE_WEBHOOK", raising=False)
    orig_secret = _line_notifier.config.get("channel_secret")
    test_secret = "phase1_test_line_secret_999"
    _line_notifier.config["channel_secret"] = test_secret
    body = b'{"events":[]}'
    client = TestClient(app)

    try:
        # Missing signature header -> 400
        res_missing = client.post("/callback", content=body, headers={"Content-Type": "application/json"})
        assert res_missing.status_code == 400
        assert "Invalid LINE webhook signature" in res_missing.json()["detail"]

        # Invalid signature -> 400
        res_bad = client.post(
            "/callback",
            content=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": "forged_sig"},
        )
        assert res_bad.status_code == 400

        # Valid HMAC signature -> 200
        raw_hmac = hmac.new(test_secret.encode("utf-8"), body, hashlib.sha256).digest()
        valid_sig = base64.b64encode(raw_hmac).decode("utf-8")
        res_valid = client.post(
            "/callback",
            content=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": valid_sig},
        )
        assert res_valid.status_code == 200
        assert res_valid.json()["status"] == "ok"
    finally:
        if orig_secret is not None:
            _line_notifier.config["channel_secret"] = orig_secret
        else:
            _line_notifier.config.pop("channel_secret", None)


def test_line_webhook_explicit_test_mode(monkeypatch):
    """Explicit ALLOW_INSECURE_LINE_WEBHOOK=true allows local offline test execution without signature."""
    monkeypatch.setenv("ALLOW_INSECURE_LINE_WEBHOOK", "true")
    orig_secret = _line_notifier.config.pop("channel_secret", None)
    client = TestClient(app)
    try:
        res = client.post("/callback", json={"events": []})
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
    finally:
        if orig_secret is not None:
            _line_notifier.config["channel_secret"] = orig_secret


# =====================================================================
# 2. Default Admin Weak PIN Detection & Strong Passphrase Support
# =====================================================================

def test_admin_weak_pin_warning_and_strong_passphrase(tmp_path):
    # 1. Test fresh profile manager detects default weak PIN 0000
    db = tmp_path / "fresh_profiles.sqlite3"
    pm_fresh = ProfileManager(db_path=db)
    assert pm_fresh.is_default_admin_pin() is True

    # 2. Test API behavior on live database
    pm = ProfileManager()
    default_p = pm.get_profile(DEFAULT_PROFILE_ID)
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:6]

    # Verify that updating admin to strong passphrase works
    # Create an admin session directly
    admin_token = session_manager.create_session(default_p)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Temporarily set admin PIN to 0000 to test warning detection
    pm.admin_reset_pin("default", new_pin_code="0000")
    assert pm.is_default_admin_pin() is True

    try:
        # Login with weak 0000 PIN returns requires_pin_change=True with warning
        res_login = client.post(
            "/api/profiles/login",
            json={"identifier": "default", "pin_code": "0000"},
        )
        assert res_login.status_code == 200
        data = res_login.json()
        assert data["requires_pin_change"] is True
        assert "安全警告" in data["warning"]
        token = data["token"]

        # Update admin PIN to strong passphrase (alphanumeric with symbol, e.g. 14 chars)
        strong_pwd = f"Admin@Secure_{suffix}"
        update_res = client.post(
            "/api/profiles/update",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "profile_id": "default",
                "current_pin": "0000",
                "new_pin": strong_pwd,
            },
        )
        assert update_res.status_code == 200
        new_token = update_res.json().get("token")
        assert new_token is not None

        # Subsequent login with strong passphrase has requires_pin_change=False
        strong_login = client.post(
            "/api/profiles/login",
            json={"identifier": "default", "pin_code": strong_pwd},
        )
        assert strong_login.status_code == 200
        assert strong_login.json()["requires_pin_change"] is False
    finally:
        # Restore admin PIN back to 0000
        pm.admin_reset_pin("default", new_pin_code="0000")


# =====================================================================
# 3. Anti-Brute-Force Rate Limiting & Lockout
# =====================================================================

def test_login_rate_limiting_and_lockout():
    """Verify that 5 failed attempts locks out the account/IP with HTTP 429."""
    ident = "brute_force_target_user"
    client = TestClient(app)

    # Attempts 1 to 4 should be 401 Unauthorized
    for i in range(1, 5):
        res = client.post("/api/profiles/login", json={"identifier": ident, "pin_code": "9999"})
        assert res.status_code == 401
        assert "剩餘嘗試次數" in res.json()["detail"]

    # 5th failed attempt triggers 429 Too Many Requests with Retry-After header
    res_lock = client.post("/api/profiles/login", json={"identifier": ident, "pin_code": "9999"})
    assert res_lock.status_code == 429
    assert "安全鎖定" in res_lock.json()["detail"]
    assert "Retry-After" in res_lock.headers
    retry_sec = int(res_lock.headers["Retry-After"])
    assert retry_sec > 800

    # 6th attempt is blocked immediately without checking credentials
    res_blocked = client.post("/api/profiles/login", json={"identifier": ident, "pin_code": "0000"})
    assert res_blocked.status_code == 429
    assert "安全鎖定" in res_blocked.json()["detail"]


def test_verify_pin_rate_limiting_and_lockout():
    """Verify that /api/profiles/verify_pin also enforces brute-force protection."""
    pid = "default"
    client = TestClient(app)

    for _ in range(4):
        res = client.post("/api/profiles/verify_pin", json={"profile_id": pid, "pin_code": "9999"})
        assert res.status_code == 401

    res_5 = client.post("/api/profiles/verify_pin", json={"profile_id": pid, "pin_code": "9999"})
    assert res_5.status_code == 429
    assert "安全鎖定" in res_5.json()["detail"]


# =====================================================================
# 4. Profile Information Exposure Boundaries
# =====================================================================

def test_profile_exposure_protection():
    """Unauthenticated users should only see minimal public id/name for login selector."""
    suffix = uuid.uuid4().hex[:6]
    client = TestClient(app)

    # Register a test profile with specific weekly budget cap
    reg_res = client.post(
        "/api/profiles/register",
        json={"name": f"隱私玩家_{suffix}", "weekly_play_cap": 888.0, "pin_code": "7777"},
    )
    assert reg_res.status_code == 200
    user_token = reg_res.json()["token"]
    user_pid = reg_res.json()["profile"]["id"]

    try:
        # 1. Unauthenticated client (no cookies / headers)
        unauth_client = TestClient(app)
        unauth_res = unauth_client.get("/api/profiles")
        assert unauth_res.status_code == 200
        profs = unauth_res.json()["profiles"]
        assert len(profs) >= 2
        for p in profs:
            assert "id" in p
            assert "name" in p
            assert "weekly_play_cap" not in p
            assert "created_at" not in p
            assert "pin_code" not in p

        # 2. GET /api/profiles/public_list returns minimal structure
        pub_res = unauth_client.get("/api/profiles/public_list")
        assert pub_res.status_code == 200
        pub_profs = pub_res.json()["profiles"]
        for p in pub_profs:
            assert set(p.keys()) == {"id", "name"}

        # 3. Regular user authenticated GET /api/profiles returns ONLY their own profile
        user_headers = {"Authorization": f"Bearer {user_token}"}
        user_res = unauth_client.get("/api/profiles", headers=user_headers)
        assert user_res.status_code == 200
        user_profs = user_res.json()["profiles"]
        assert len(user_profs) == 1
        assert user_profs[0]["id"] == user_pid
        assert user_profs[0]["weekly_play_cap"] == 888.0

        # 4. Admin authenticated GET /api/profiles returns all profiles
        pm = ProfileManager()
        admin_p = pm.get_profile(DEFAULT_PROFILE_ID)
        admin_token = session_manager.create_session(admin_p)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        admin_res = unauth_client.get("/api/profiles", headers=admin_headers)
        assert admin_res.status_code == 200
        admin_profs = admin_res.json()["profiles"]
        assert len(admin_profs) >= 2
        assert any(p["id"] == user_pid and p["weekly_play_cap"] == 888.0 for p in admin_profs)
    finally:
        pm = ProfileManager()
        try:
            pm.admin_delete_profile(user_pid)
        except Exception:
            pass


# =====================================================================
# 5. System Storage Status API Protection & Path Masking
# =====================================================================

def test_system_storage_status_access_control():
    suffix = uuid.uuid4().hex[:6]
    unauth_client = TestClient(app)

    # 1. Unauthenticated access -> 401
    unauth_res = unauth_client.get("/api/system/storage_status")
    assert unauth_res.status_code == 401

    # 2. Regular user access -> 403 Forbidden
    reg_client = TestClient(app)
    reg_res = reg_client.post(
        "/api/profiles/register",
        json={"name": f"系統測試員_{suffix}", "weekly_play_cap": 200.0, "pin_code": "1234"},
    )
    user_token = reg_res.json()["token"]
    user_pid = reg_res.json()["profile"]["id"]
    try:
        user_res = unauth_client.get(
            "/api/system/storage_status",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_res.status_code == 403
        assert "權限不足" in user_res.json()["detail"]

        # 3. Admin user access -> 200 and path is masked
        pm = ProfileManager()
        admin_p = pm.get_profile(DEFAULT_PROFILE_ID)
        admin_token = session_manager.create_session(admin_p)
        admin_res = unauth_client.get(
            "/api/system/storage_status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_res.status_code == 200
        data = admin_res.json()
        assert "storage_root" in data
        assert "stats" in data
        # Ensure raw Windows absolute path is not leaked
        assert not data["storage_root"].startswith("C:\\")
        assert not data["storage_root"].startswith("/Users/")
        assert data["storage_root"].startswith(".../")
    finally:
        pm = ProfileManager()
        try:
            pm.admin_delete_profile(user_pid)
        except Exception:
            pass


# =====================================================================
# 6. Session Lifecycle, HttpOnly Cookies & Instant Revocation
# =====================================================================

def test_session_lifecycle_httponly_cookie_and_revocation():
    suffix = uuid.uuid4().hex[:6]
    client = TestClient(app)

    # 1. Register a player and verify cookie is set in response
    reg_res = client.post(
        "/api/profiles/register",
        json={"name": f"會話生命員_{suffix}", "weekly_play_cap": 500.0, "pin_code": "3333"},
    )
    assert reg_res.status_code == 200
    token = reg_res.json()["token"]
    pid = reg_res.json()["profile"]["id"]

    # Verify Set-Cookie header contains HttpOnly and auth_session_token
    cookie_header = reg_res.headers.get("set-cookie", "")
    assert "auth_session_token=" in cookie_header
    assert "HttpOnly" in cookie_header

    # 2. Authenticate using Cookie alone (without Authorization header)
    cookie_client = TestClient(app, cookies={"auth_session_token": token})
    me_res = cookie_client.get("/api/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["profile"]["id"] == pid

    # 3. Updating PIN must revoke all previous session tokens across all devices
    update_res = client.post(
        "/api/profiles/update",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "profile_id": pid,
            "current_pin": "3333",
            "new_pin": "4444",
        },
    )
    assert update_res.status_code == 200
    new_token = update_res.json().get("token")
    assert new_token is not None and new_token != token

    # Prior session token is immediately invalid (401)
    clean_client = TestClient(app)
    old_token_res = clean_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert old_token_res.status_code == 401

    # New session token works
    new_token_res = clean_client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_token_res.status_code == 200

    # 4. Admin resetting player PIN revokes all player sessions
    pm = ProfileManager()
    admin_p = pm.get_profile(DEFAULT_PROFILE_ID)
    admin_token = session_manager.create_session(admin_p)
    admin_reset_res = clean_client.post(
        "/api/admin/players/reset_pin",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"profile_id": pid, "new_pin": "5555"},
    )
    assert admin_reset_res.status_code == 200

    # The player's token is revoked immediately
    after_admin_reset = clean_client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert after_admin_reset.status_code == 401

    # 5. Clean up
    try:
        pm.admin_delete_profile(pid)
    except Exception:
        pass


# =====================================================================
# 7. CORS Configuration Convergence
# =====================================================================

def test_cors_configuration():
    """Verify CORS origins are validated and wildcard '*' is not used with credentials."""
    client = TestClient(app)
    # Whitelisted origin
    res_allowed = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_allowed.status_code == 200
    assert res_allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert res_allowed.headers.get("access-control-allow-credentials") == "true"
    # Never wildcard with credentials
    assert res_allowed.headers.get("access-control-allow-origin") != "*"

    # Disallowed external origin should not be granted access-control-allow-origin
    res_disallowed = client.options(
        "/api/health",
        headers={
            "Origin": "https://malicious-external-website.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_disallowed.headers.get("access-control-allow-origin") is None
