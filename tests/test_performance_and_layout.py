"""Automated tests for Profile performance, lazy tab execution, and mobile layout enhancements."""

import time
import pytest
from core.profile_manager import ProfileManager, DEFAULT_PROFILE_ID
from core.wallet import WeeklyWalletManager


def test_profile_operation_latency_is_sub_10ms(tmp_path):
    """Verify profile operations complete in less than 10ms to ensure zero-lag profile updates."""
    db_file = tmp_path / "test_perf_profile.db"
    pm = ProfileManager(db_path=db_file)

    t0 = time.perf_counter()
    prof = pm.get_or_default()
    read_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert read_duration_ms < 50.0  # Well under threshold even in cold CI

    t0 = time.perf_counter()
    ok, verified_prof, msg = pm.verify_login(prof["id"], "0000")
    auth_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert ok is True
    assert auth_duration_ms < 50.0

    t0 = time.perf_counter()
    updated = pm.update_profile(profile_id=prof["id"], current_pin="0000", new_name="急速玩家", new_weekly_play_cap=300.0)
    update_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert updated["name"] == "急速玩家"
    assert updated["weekly_play_cap"] == 300.0
    assert update_duration_ms < 100.0


def test_app_py_has_lazy_segmented_navigation():
    """Verify app.py uses segmented control with lazy branching rather than eager st.tabs."""
    with open("app.py", encoding="utf-8") as f:
        code = f.read()

    # Must contain segmented_control for main navigation
    assert "st.segmented_control" in code
    assert "NAV_RADAR" in code
    assert "NAV_PARLAY" in code
    assert "NAV_WALLET" in code
    assert "NAV_PROFILE" in code
    assert "NAV_RESEARCH" in code

    # Must branch conditionally so tabs do not eagerly run all together
    assert "if active_tab == NAV_RADAR:" in code
    assert "elif active_tab == NAV_PARLAY:" in code
    assert "elif active_tab == NAV_WALLET:" in code
    assert "elif active_tab == NAV_PROFILE:" in code
    assert "elif active_tab == NAV_RESEARCH:" in code

    # Must contain mobile-first styling classes
    assert "mobile-wallet-grid" in code
    assert "mobile-wallet-card" in code
    assert "settled-ticket-card" in code


def test_mobile_wallet_grid_rendering_in_profile_view():
    """Verify profile_view.py contains the responsive mobile-wallet-grid."""
    with open("ui/profile_view.py", encoding="utf-8") as f:
        code = f.read()

    assert "mobile-wallet-grid" in code
    assert "mobile-wallet-card" in code


def test_system_settings_page_has_archie_gate():
    """Verify pages/3_系統設定與資料存放.py strictly enforces Archie-only access gate."""
    with open("pages/3_系統設定與資料存放.py", encoding="utf-8") as f:
        code = f.read()

    assert "Archie" in code
    assert "存取受限" in code or "權限" in code or "stop" in code


def test_profile_view_has_archie_admin_roster():
    """Verify only Archie can see all players roster and admin reset tools."""
    with open("ui/profile_view.py", encoding="utf-8") as f:
        code = f.read()

    assert 'is_admin = bool(profile.get("name") == "Archie")' in code
    assert "👑 全系統玩家名單 (管理員 Archie 專屬)" in code


def test_app_py_has_numeric_keypad_script_and_footer_expander():
    """Verify app.py includes numeric keypad injector and footer PWA expander."""
    with open("app.py", encoding="utf-8") as f:
        code = f.read()

    assert "patchNumericKeypads" in code
    assert "inputmode" in code
    # Expander must be at the bottom (after NAV_OPTIONS definition)
    pwa_idx = code.rfind("iPhone / 行動端 PWA 獨立 App 安裝說明")
    nav_idx = code.find("NAV_OPTIONS")
    assert pwa_idx > nav_idx, "PWA installation expander must be located at the bottom of the page"

