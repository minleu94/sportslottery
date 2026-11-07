"""Authenticated LINE Profile routes, isolated from live app services."""

import inspect
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, params

from core.line_notifier import LineNotifier
from server import service_registry
from server.auth import require_authenticated_session, verify_profile_ownership
from server.routers import line as line_routes


class _ImmediateAwaitable:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def __await__(self):
        if False:
            yield None
        if self.error:
            raise self.error
        return self.value


class _ImmediateStream:
    def __init__(self, body):
        self.body = body
        self.sent = False

    def __aiter__(self):
        return self

    def __anext__(self):
        if self.sent:
            return _ImmediateAwaitable(error=StopAsyncIteration())
        self.sent = True
        return _ImmediateAwaitable(self.body)


class _MockRequest:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {"content-length": str(len(body))}

    def stream(self):
        return _ImmediateStream(self.body)


def _drive_immediate(coroutine):
    try:
        result = coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError(f"Route unexpectedly awaited external work: {result!r}")


class FakeProfiles:
    def __init__(self):
        self.profiles = [
            {"id": "p-a", "name": "玩家甲", "line_user_id": None},
            {"id": "p-b", "name": "玩家乙", "line_user_id": None},
        ]

    def get_profile(self, profile_id):
        return next((dict(row) for row in self.profiles if row["id"] == profile_id), None)

    def get_profile_by_name(self, name):
        return next((dict(row) for row in self.profiles if row["name"] == name), None)

    def get_profile_by_line_user_id(self, line_user_id):
        return next((dict(row) for row in self.profiles if row.get("line_user_id") == line_user_id), None)

    def bind_line_user_from_authenticated_session(self, profile_id, line_user_id):
        owner = self.get_profile_by_line_user_id(line_user_id)
        if owner and owner["id"] != profile_id:
            raise ValueError("此 LINE 帳號已綁定其他 Profile")
        profile = next(row for row in self.profiles if row["id"] == profile_id)
        profile["line_user_id"] = line_user_id
        return dict(profile)

    def unbind_line_user_from_authenticated_session(self, profile_id):
        profile = next(row for row in self.profiles if row["id"] == profile_id)
        profile["line_user_id"] = None
        return True


def test_line_routes_require_authenticated_session_and_profile_ownership():
    parameter = inspect.signature(line_routes.get_line_preferences).parameters["session"]
    assert isinstance(parameter.default, params.Depends)
    assert parameter.default.dependency is require_authenticated_session
    with pytest.raises(HTTPException) as error:
        verify_profile_ownership("p-a", {"profile_id": "p-b"})
    assert error.value.status_code == 403
    status_path = next(route.path for route in line_routes.router.routes if route.name == "line_service_status")
    assert status_path == "/api/line/status"


def test_line_preferences_and_binding_approval_are_profile_scoped(monkeypatch, tmp_path):
    profiles = FakeProfiles()
    notifier = LineNotifier(config_path=tmp_path / "line.yaml", profile_manager=profiles)
    monkeypatch.setattr(line_routes, "_line_notifier", notifier)
    monkeypatch.setattr(service_registry, "get_services", lambda: SimpleNamespace(profile_mgr=profiles))

    unbound = line_routes.get_line_preferences({"profile_id": "p-a"})
    assert unbound["bound"] is False
    assert unbound["preferences"]["steam_drop"] is True

    request = notifier.request_line_binding("玩家甲", "U-REQUEST")
    assert request["success"]
    request_id = notifier.list_line_binding_requests("p-a")[0]["request_id"]
    assert notifier.list_line_binding_requests("p-b") == []
    assert notifier.approve_line_binding_request("p-b", request_id) is False
    assert notifier.list_line_binding_requests("p-a")
    assert notifier.approve_line_binding_request("p-a", request_id) is True
    assert profiles.get_profile("p-a")["line_user_id"] == "U-REQUEST"

    preferences = notifier.update_notification_preferences("U-REQUEST", {"steam_drop": False, "morning_radar": True})
    assert preferences["steam_drop"] is False
    assert preferences["morning_radar"] is True
    assert notifier.get_notification_preferences("p-b")["steam_drop"] is True
    assert line_routes.get_line_preferences({"profile_id": "p-a"})["bound"] is True

    line_routes.unbind_line_profile({"profile_id": "p-a"})
    assert profiles.get_profile("p-a")["line_user_id"] is None


def test_line_preference_updates_bound_request_body_size(monkeypatch, tmp_path):
    profiles = FakeProfiles()
    profiles.profiles[0]["line_user_id"] = "U-BOUND"
    notifier = LineNotifier(config_path=tmp_path / "line.yaml", profile_manager=profiles)
    monkeypatch.setattr(line_routes, "_line_notifier", notifier)
    monkeypatch.setattr(service_registry, "get_services", lambda: SimpleNamespace(profile_mgr=profiles))

    payload = json.dumps({"steam_drop": False}).encode()
    response = _drive_immediate(line_routes.put_line_preferences(
        _MockRequest(payload), {"profile_id": "p-a"},
    ))
    assert response["preferences"]["steam_drop"] is False

    with pytest.raises(HTTPException) as declared_error:
        _drive_immediate(line_routes.put_line_preferences(
            _MockRequest(b"", headers={"content-length": str(line_routes.MAX_LINE_PREFERENCES_BODY_BYTES + 1)}),
            {"profile_id": "p-a"},
        ))
    assert declared_error.value.status_code == 413

    with pytest.raises(HTTPException) as streamed_error:
        _drive_immediate(line_routes.put_line_preferences(
            _MockRequest(b"x" * (line_routes.MAX_LINE_PREFERENCES_BODY_BYTES + 1), headers={}),
            {"profile_id": "p-a"},
        ))
    assert streamed_error.value.status_code == 413
