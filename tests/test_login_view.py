#!/usr/bin/env python3
"""Tests for login_view component and Profile authentication gate."""

import pytest
from unittest.mock import MagicMock, patch
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from ui.login_view import render_login_gate, verify_profile_login


def test_login_gate_authenticated_session(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    p = pm.create_profile(name="阿榮", weekly_play_cap=300.0, pin_code="6666")

    # When authenticated_profile_id is set in session_state
    mock_session = {"authenticated_profile_id": p["id"]}
    with patch("ui.login_view.st.session_state", mock_session):
        active = render_login_gate(pm)
        assert active is not None
        assert active["name"] == "阿榮"
        assert active["id"] == p["id"]
        assert mock_session["active_profile_id"] == p["id"]


def test_login_gate_unauthenticated_session(tmp_path):
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)

    # Empty session state
    mock_session = {}
    with patch("ui.login_view.st.session_state", mock_session), \
         patch("ui.login_view.st.tabs", return_value=[MagicMock(), MagicMock(), MagicMock()]), \
         patch("ui.login_view.st.form"), \
         patch("ui.login_view.st.form_submit_button", return_value=False), \
         patch("ui.login_view.st.selectbox", return_value=DEFAULT_PROFILE_ID), \
         patch("ui.login_view.st.text_input", return_value=""), \
         patch("ui.login_view.st.button", return_value=False), \
         patch("ui.login_view.st.markdown"), \
         patch("ui.login_view.st.columns", side_effect=lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]):
        active = render_login_gate(pm)
        assert active is None


def test_verify_profile_login_fallback(tmp_path):
    """Test verify_profile_login even if verify_login attribute is absent from the instance."""
    db = tmp_path / "test_profiles.sqlite3"
    pm = ProfileManager(db_path=db)
    p = pm.create_profile(name="大明", weekly_play_cap=200.0, pin_code="1234")

    # Create dummy mock that lacks verify_login
    dummy = MagicMock(spec=["get_profile", "verify_pin", "list_profiles"])
    dummy.get_profile.return_value = p
    dummy.verify_pin.side_effect = lambda pid, pin: pin == "1234"
    dummy.list_profiles.return_value = [p]

    # Correct PIN
    ok, prof, msg = verify_profile_login(dummy, p["id"], "1234")
    assert ok is True
    assert prof["name"] == "大明"

    # Wrong PIN
    ok_fail, _, msg_fail = verify_profile_login(dummy, p["id"], "0000")
    assert ok_fail is False
    assert "PIN 碼不正確" in msg_fail


def test_login_view_has_forgot_password_contact():
    """Verify login_view.py source contains forgot password button and contact admin Archie prompt."""
    with open("ui/login_view.py", encoding="utf-8") as f:
        content = f.read()
    assert "忘記密碼" in content
    assert "Archie" in content
    assert "inputmode" in content  # Numeric keypad script check
    assert "pattern" in content


def test_login_view_has_no_profile_selectbox():
    """Ensure login_view.py does not contain selectbox for choosing other players' profiles."""
    with open("ui/login_view.py", encoding="utf-8") as f:
        content = f.read()
    # There should be no selectbox in login or change pin tab
    assert "st.selectbox" not in content, "Login view should not expose player names in selectbox dropdowns"


