"""First-run network exposure policy for the built-in administrator account."""

from __future__ import annotations

from typing import Any


def network_access_enabled(profile_manager: Any | None = None) -> bool:
    """Allow LAN/tunnel listeners only after the default administrator PIN is changed."""
    try:
        if profile_manager is None:
            from core.profile_manager import DEFAULT_PROFILE_ID, ProfileManager

            profile_manager = ProfileManager()
        else:
            from core.profile_manager import DEFAULT_PROFILE_ID

        if not profile_manager.get_profile(DEFAULT_PROFILE_ID):
            return False
        return not bool(profile_manager.is_default_admin_pin())
    except Exception:
        # A database or credential-state error must not expose the service remotely.
        return False
