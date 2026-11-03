import sqlite3

from core.bootstrap_security import network_access_enabled
from core.profile_manager import DEFAULT_PROFILE_ID, ProfileManager


def test_remote_access_stays_disabled_until_admin_default_pin_changes(tmp_path):
    manager = ProfileManager(db_path=tmp_path / "profiles.sqlite3")
    assert manager.is_default_admin_pin() is True
    assert network_access_enabled(manager) is False

    manager.update_profile(DEFAULT_PROFILE_ID, current_pin="0000", new_pin_code="24681357")
    assert manager.is_default_admin_pin() is False
    assert network_access_enabled(manager) is True


def test_remote_access_fails_closed_when_profile_state_is_unavailable():
    class BrokenProfileManager:
        def get_profile(self, _profile_id):
            raise RuntimeError("unavailable")

    assert network_access_enabled(BrokenProfileManager()) is False


def test_remote_access_fails_closed_for_invalid_admin_pin_state(tmp_path):
    manager = ProfileManager(db_path=tmp_path / "profiles.sqlite3")
    for invalid_credential in ("", "1234", "not-a-pin", "pbkdf2:sha256:100000:broken:broken"):
        with sqlite3.connect(tmp_path / "profiles.sqlite3") as conn:
            conn.execute(
                "UPDATE profiles SET pin_code = ? WHERE id = ?",
                (invalid_credential, DEFAULT_PROFILE_ID),
            )

        assert manager.is_default_admin_pin() is True
        assert network_access_enabled(manager) is False
