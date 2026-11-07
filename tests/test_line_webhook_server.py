"""Mock-only LINE webhook signature and event processing tests."""

import base64
import base64
import hashlib
import hmac
import inspect
import json
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks, HTTPException

import core.line_notifier as line_notifier_module
from scripts.line_webhook_server import app as unified_app, notifier, process_events, verify_signature
from server.routers import line as line_routes


@pytest.fixture(autouse=True)
def isolate_runtime_and_services(monkeypatch):
    monkeypatch.setattr(line_notifier_module, "load_active_runtime", lambda _path: {})


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
    raise AssertionError(f"Webhook unexpectedly awaited external work: {result!r}")


def test_webhook_router_is_shared_with_main_api():
    from server.api import app as server_api_app

    assert unified_app is server_api_app
    assert any(getattr(route, "original_router", None) is line_routes.router for route in unified_app.routes)
    assert inspect.iscoroutinefunction(line_routes.line_service_status)


def test_webhook_signature_hmac_accepts_only_exact_body_signature():
    secret = "mock-secret"
    body = b'{"events":[]}'
    valid = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    assert verify_signature(body, valid, secret) is True
    assert verify_signature(body, "wrong", secret) is False
    assert verify_signature(body, valid, "") is False
    assert verify_signature(body + b" ", valid, secret) is False


def test_webhook_callback_accepts_valid_signature_and_rejects_invalid_signature(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_LINE_WEBHOOK", raising=False)
    secret = "mock-webhook-secret"
    body = json.dumps({"events": []}).encode()
    old_secret = notifier.config.get("channel_secret")
    notifier.config["channel_secret"] = secret
    valid = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    try:
        response = _drive_immediate(line_routes.line_webhook_callback(
            _MockRequest(body), BackgroundTasks(), valid,
        ))
        assert response == {"status": "ok", "events_processed": 0}
        with pytest.raises(HTTPException) as error:
            _drive_immediate(line_routes.line_webhook_callback(
                _MockRequest(body), BackgroundTasks(), "bad-signature",
            ))
        assert error.value.status_code == 400
    finally:
        if old_secret is None:
            notifier.config.pop("channel_secret", None)
        else:
            notifier.config["channel_secret"] = old_secret


def test_webhook_callback_enforces_body_size_cap():
    with pytest.raises(HTTPException) as error:
        _drive_immediate(line_routes.line_webhook_callback(
            _MockRequest(b"", headers={"content-length": str(line_routes.MAX_LINE_WEBHOOK_BODY_BYTES + 1)}),
            BackgroundTasks(),
            None,
        ))
    assert error.value.status_code == 413


def test_webhook_event_routes_flex_and_quick_replies_without_global_recipient():
    event = {
        "webhookEventId": "event-menu-test",
        "replyToken": "test-reply-token",
        "type": "message",
        "source": {"type": "user", "userId": "U-MOCK"},
        "message": {"type": "text", "text": "功能表"},
    }
    notifier.release_webhook_event("event-menu-test")
    with patch.object(notifier, "reply_message", return_value={"success": True}) as reply:
        process_events([event])
    assert reply.call_count == 1
    payload = reply.call_args.kwargs
    assert payload["reply_token"] == "test-reply-token"
    assert payload["flex_message"]["type"] == "flex"
    assert len(payload["quick_replies"]) >= 6
    assert "user_id" not in notifier.config


def test_webhook_follow_event_sends_safe_welcome_menu():
    event = {
        "replyToken": "welcome-token",
        "type": "follow",
        "source": {"type": "user", "userId": "U-NEW"},
    }
    with patch.object(notifier, "reply_message", return_value={"success": True}) as reply:
        process_events([event])
    payload = reply.call_args.kwargs
    assert "歡迎使用" in payload["text"]
    assert "私人 Wallet 需先綁定 Profile" in payload["text"]
    assert payload["flex_message"]["type"] == "flex"


def test_private_wallet_commands_are_not_answered_in_group_chats():
    event = {
        "webhookEventId": "event-group-wallet-test",
        "replyToken": "token-group-wallet",
        "type": "message",
        "source": {"type": "group", "groupId": "G-MOCK", "userId": "U-BOUND"},
        "message": {"type": "text", "text": "查戰績"},
    }
    with patch.object(notifier, "handle_user_message_full") as handle_message, patch.object(
        notifier, "reply_message", return_value={"success": True},
    ) as reply:
        process_events([event])
    handle_message.assert_not_called()
    assert reply.call_args.kwargs["text"] == "私人 Wallet、通知與帳號設定請在 LINE 官方帳號的一對一聊天使用。"


def test_duplicate_webhook_event_is_processed_once():
    event = {
        "webhookEventId": "event-dedupe-test",
        "replyToken": "token-dedupe",
        "type": "message",
        "source": {"type": "user", "userId": "U-Dedupe"},
        "message": {"type": "text", "text": "功能表"},
    }
    notifier.release_webhook_event("event-dedupe-test")
    result = {"text": "menu", "flex_message": None, "quick_replies": notifier.default_quick_replies()}
    with patch.object(notifier, "handle_user_message_full", return_value=result) as handle_message, patch.object(
        notifier, "reply_message", return_value={"success": True}
    ) as reply:
        process_events([event])
        process_events([event])
    assert handle_message.call_count == 1
    assert reply.call_count == 1


def test_failed_webhook_processing_releases_event_for_retry():
    event = {
        "webhookEventId": "event-retry-test",
        "replyToken": "token-retry",
        "type": "message",
        "source": {"type": "user", "userId": "U-Retry"},
        "message": {"type": "text", "text": "功能表"},
    }
    notifier.release_webhook_event("event-retry-test")
    result = {"text": "menu", "flex_message": None, "quick_replies": notifier.default_quick_replies()}
    with patch.object(notifier, "handle_user_message_full", side_effect=[RuntimeError("mock failure"), result]) as handle_message, patch.object(
        notifier, "reply_message", return_value={"success": True}
    ) as reply:
        process_events([event])
        process_events([event])
    assert handle_message.call_count == 2
    assert reply.call_count == 1
