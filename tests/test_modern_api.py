"""Comprehensive test suite for the modern FastAPI backend, session authentication, and SPA integration."""

import base64
import hashlib
import hmac
import pytest
from fastapi.testclient import TestClient
from server.api import app, _line_notifier
from core.profile_manager import ProfileManager, hash_pin_code, verify_pin_code, PBKDF2_PREFIX
from core.wallet import WeeklyWalletManager

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "strategy_metadata" in data
    assert "alliances" in data


def test_auth_and_session_lifecycle():
    import uuid
    suffix = uuid.uuid4().hex[:6]

    # 1. Unauthenticated access to protected route must be rejected with 401
    unauth_res = client.get("/api/wallet/status?profile_id=default")
    assert unauth_res.status_code == 401
    assert "未授權存取" in unauth_res.json()["detail"]

    # 2. Register a new test player to test full login and session lifecycle
    reg_res = client.post(
        "/api/profiles/register",
        json={"name": f"會話測試員_{suffix}", "weekly_play_cap": 300.0, "pin_code": "4321"},
    )
    assert reg_res.status_code == 200
    reg_data = reg_res.json()
    assert reg_data["success"] is True
    pid = reg_data["profile"]["id"]
    token = reg_data["token"]
    assert len(token) >= 32

    # 3. Access protected route with Bearer token
    headers = {"Authorization": f"Bearer {token}"}
    auth_res = client.get(f"/api/wallet/status?profile_id={pid}", headers=headers)
    assert auth_res.status_code == 200
    w_data = auth_res.json()
    assert "weekly_wallet_balance" in w_data
    assert w_data["weekly_play_cap"] == 300.0

    # 4. Verify /api/auth/me returns current session user and does not leak PIN
    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["profile"]["id"] == pid
    assert "pin_code" not in me_data["profile"]

    # 5. Create a separate non-admin player and test cross-user access restriction (403)
    user_b_res = client.post(
        "/api/profiles/register",
        json={"name": f"隔離玩家B_{suffix}", "weekly_play_cap": 250.0, "pin_code": "9876"},
    )
    assert user_b_res.status_code == 200
    token_b = user_b_res.json()["token"]
    pid_b = user_b_res.json()["profile"]["id"]

    # User B attempting to view User A's wallet should be forbidden with 403
    headers_b = {"Authorization": f"Bearer {token_b}"}
    forbidden_res = client.get(f"/api/wallet/status?profile_id={pid}", headers=headers_b)
    assert forbidden_res.status_code == 403
    assert "權限不足" in forbidden_res.json()["detail"]

    # User B can view their own wallet
    own_res = client.get(f"/api/wallet/status?profile_id={pid_b}", headers=headers_b)
    assert own_res.status_code == 200
    assert own_res.json()["weekly_play_cap"] == 250.0

    # 6. Logout invalidates session
    logout_res = client.post("/api/profiles/logout", headers=headers_b)
    assert logout_res.status_code == 200
    after_logout = client.get("/api/auth/me", headers=headers_b)
    assert after_logout.status_code == 401


def test_salted_pbkdf2_pin_storage_and_migration():
    pm = ProfileManager()
    default_p = pm.get_profile("default")
    assert default_p is not None

    # Verify that PIN is stored as salted PBKDF2 hash, not plaintext
    stored_pin = default_p["pin_code"]
    assert stored_pin.startswith(PBKDF2_PREFIX)
    assert len(stored_pin) > 40

    # Test auto-upgrade of legacy plaintext PIN in SQLite
    legacy_pid = "p_test_legacy_migration"
    with pm._transaction() as conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (legacy_pid,))
        conn.execute(
            """INSERT INTO profiles (id, name, weekly_play_cap, pin_code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (legacy_pid, "傳統舊玩家", 200.0, "5678", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )

    # Verify that verifying the legacy PIN succeeds AND transparently upgrades the row to a salted hash
    assert pm.verify_pin(legacy_pid, "5678") is True
    upgraded_p = pm.get_profile(legacy_pid)
    assert upgraded_p["pin_code"].startswith(PBKDF2_PREFIX)
    assert verify_pin_code("5678", upgraded_p["pin_code"]) is True
    assert verify_pin_code("0000", upgraded_p["pin_code"]) is False


def test_update_profile_e2e():
    """Verify that ProfileManager update_profile argument mismatch is fixed and works via API."""
    import uuid
    suffix = uuid.uuid4().hex[:6]

    # 1. Create a dedicated profile for updating
    reg_res = client.post(
        "/api/profiles/register",
        json={"name": f"即將更新玩家_{suffix}", "weekly_play_cap": 250.0, "pin_code": "1111"},
    )
    assert reg_res.status_code == 200
    user_data = reg_res.json()["profile"]
    pid = user_data["id"]
    user_token = reg_res.json()["token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 2. Update profile with current_pin and new parameters
    update_res = client.post(
        "/api/profiles/update",
        headers=user_headers,
        json={
            "profile_id": pid,
            "current_pin": "1111",
            "name": f"已更新玩家名稱_{suffix}",
            "weekly_play_cap": 500.0,
            "new_pin": "2222",
        },
    )
    assert update_res.status_code == 200, f"Update failed: {update_res.text}"
    updated_profile = update_res.json()["profile"]
    assert updated_profile["name"] == f"已更新玩家名稱_{suffix}"
    assert updated_profile["weekly_play_cap"] == 500.0

    # 3. Verify old PIN is rejected and new PIN works
    bad_login = client.post("/api/profiles/login", json={"identifier": pid, "pin_code": "1111"})
    assert bad_login.status_code == 401

    good_login = client.post("/api/profiles/login", json={"identifier": pid, "pin_code": "2222"})
    assert good_login.status_code == 200
    assert good_login.json()["success"] is True


def test_place_and_settle_ticket_e2e():
    """Verify that TicketRecorder entry_mode='frontend_api' conflict is resolved and tickets settle correctly."""
    import uuid
    suffix = uuid.uuid4().hex[:6]

    # 1. Register a new user with fresh wallet
    reg_res = client.post(
        "/api/profiles/register",
        json={"name": f"下注測試員_{suffix}", "weekly_play_cap": 1000.0, "pin_code": "0000"},
    )
    assert reg_res.status_code == 200
    user = reg_res.json()["profile"]
    pid = user["id"]
    token = reg_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Deposit external funds to enable betting
    dep_res = client.post(
        "/api/wallet/deposit",
        headers=headers,
        json={"profile_id": pid, "amount": 200.0, "notes": "測試開戶儲值"},
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["wallet_status"]["weekly_wallet_balance"] == 200.0

    # 3. Place a 2-leg parlay ticket
    sample_legs = [
        {
            "game_id": "test_game_1",
            "alliance": "NBA",
            "play_type": "moneyline",
            "recommend_type": "AWAY",
            "recommend_side": "塞爾提克",
            "odds": 1.75,
            "home_team": "熱火",
            "away_team": "塞爾提克",
            "match_time": "2026-10-31 08:00",
        },
        {
            "game_id": "test_game_2",
            "alliance": "NBA",
            "play_type": "spread",
            "recommend_type": "HOME",
            "recommend_side": "金塊",
            "odds": 1.85,
            "home_team": "金塊",
            "away_team": "太陽",
            "match_time": "2026-10-31 10:30",
        },
    ]

    stake = 100.0
    combined_odds = round(1.75 * 1.85, 2)
    place_payload = {
        "profile_id": pid,
        "legs": sample_legs,
        "stake": stake,
        "placed_odds": combined_odds,
        "recommendation_odds": combined_odds,
        "parlay_name": "測試 2 串 1 組合",
    }

    # Place ticket via Web API (with entry_mode='frontend_api')
    place_res = client.post("/api/tickets/place", headers=headers, json=place_payload)
    assert place_res.status_code == 200, f"Ticket placement failed: {place_res.text}"
    place_data = place_res.json()
    assert place_data["success"] is True
    ticket_id = place_data["ticket"]["ticket_id"]
    assert isinstance(ticket_id, str) and len(ticket_id) >= 8

    # Verify wallet balance deducted
    post_wallet = place_data["wallet_status"]
    assert post_wallet["weekly_wallet_balance"] == 100.0
    assert post_wallet["weekly_staked"] == stake

    # Verify ticket in list_tickets
    list_res = client.get(f"/api/tickets?profile_id={pid}", headers=headers)
    assert list_res.status_code == 200
    tickets = list_res.json()["tickets"]
    assert any(t["ticket_id"] == ticket_id for t in tickets)

    # 4. Settle ticket as WON
    payout = round(stake * combined_odds, 2)
    settle_res = client.post(
        "/api/tickets/settle",
        headers=headers,
        json={"ticket_id": ticket_id, "result": "WON", "custom_payout": payout},
    )
    assert settle_res.status_code == 200, f"Settlement failed: {settle_res.text}"
    settle_data = settle_res.json()
    assert settle_data["success"] is True
    final_wallet = settle_data["wallet_status"]
    # Net profit goes to prize pool
    assert final_wallet["prize_pool"] >= round(payout - stake, 2)


def test_line_webhook_signature_verification():
    # 1. Local loopback / testclient call without secret should succeed
    res = client.post("/callback", json={"events": []})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 2. With channel_secret configured, invalid signature must be rejected
    orig_secret = _line_notifier.config.get("channel_secret")
    test_secret = "test_line_channel_secret_xyz123"
    try:
        _line_notifier.config["channel_secret"] = test_secret
        body_bytes = b'{"events":[]}'

        # Missing signature -> 400
        res_missing = client.post("/callback", content=body_bytes, headers={"Content-Type": "application/json"})
        assert res_missing.status_code == 400

        # Bad signature -> 400
        res_bad = client.post(
            "/callback",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Line-Signature": "invalid_sig_123"},
        )
        assert res_bad.status_code == 400

        # Valid HMAC-SHA256 signature -> 200
        raw_hmac = hmac.new(test_secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
        valid_sig = base64.b64encode(raw_hmac).decode("utf-8")
        res_valid = client.post(
            "/callback",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Line-Signature": valid_sig},
        )
        assert res_valid.status_code == 200
        assert res_valid.json()["status"] == "ok"
    finally:
        if orig_secret is not None:
            _line_notifier.config["channel_secret"] = orig_secret
        else:
            _line_notifier.config.pop("channel_secret", None)


def test_radar_and_legs():
    res_radar = client.get("/api/radar")
    assert res_radar.status_code == 200
    r_data = res_radar.json()
    assert "radar" in r_data
    assert "status_counts" in r_data
    assert isinstance(r_data["radar"], list)

    res_legs = client.get("/api/legs?limit=10")
    assert res_legs.status_code == 200
    l_data = res_legs.json()
    assert "legs" in l_data
    assert l_data["returned"] <= 10


def test_research_analytics():
    res = client.get("/api/research/analytics")
    assert res.status_code == 200
    data = res.json()
    assert "total_snapshots" in data
    assert "cohort" in data
    assert "shadow_portfolio" in data


def test_frontend_spa_serving():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert '<div id="root">' in res.text
