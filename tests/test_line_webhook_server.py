#!/usr/bin/env python3
"""Unit tests for LINE Bot FastAPI Webhook Server with mandatory cryptographic signature enforcement."""

import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from scripts.line_webhook_server import app, notifier, verify_signature


def test_webhook_root_endpoint():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert data["service"] == "sportslottery-line-bot"


def test_webhook_production_missing_secret_rejects_with_503(monkeypatch):
    """When channel_secret is not configured on server, production mode must reject callback with 503."""
    monkeypatch.delenv("ALLOW_INSECURE_LINE_WEBHOOK", raising=False)
    orig_secret = notifier.config.pop("channel_secret", None)
    try:
        client = TestClient(app)
        resp = client.post("/callback", json={"events": []})
        assert resp.status_code == 503
        assert "channel_secret is not configured" in resp.json()["detail"]
    finally:
        if orig_secret is not None:
            notifier.config["channel_secret"] = orig_secret


def test_webhook_production_signature_verification(monkeypatch):
    """When channel_secret is configured, invalid signature must be 400, and valid HMAC must be 200."""
    monkeypatch.delenv("ALLOW_INSECURE_LINE_WEBHOOK", raising=False)
    orig_secret = notifier.config.get("channel_secret")
    test_secret = "secret_key_456"
    notifier.config["channel_secret"] = test_secret
    try:
        client = TestClient(app)
        body = json.dumps({"events": []}).encode("utf-8")

        # Missing signature -> 400
        res_missing = client.post("/callback", content=body, headers={"Content-Type": "application/json"})
        assert res_missing.status_code == 400

        # Invalid signature -> 400
        res_bad = client.post(
            "/callback",
            content=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": "wrong_sig"},
        )
        assert res_bad.status_code == 400

        # Valid signature -> 200
        digest = hmac.new(test_secret.encode("utf-8"), body, hashlib.sha256).digest()
        valid_sig = base64.b64encode(digest).decode("utf-8")
        res_ok = client.post(
            "/callback",
            content=body,
            headers={"Content-Type": "application/json", "X-Line-Signature": valid_sig},
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "ok"
    finally:
        if orig_secret is not None:
            notifier.config["channel_secret"] = orig_secret
        else:
            notifier.config.pop("channel_secret", None)


@patch("scripts.line_webhook_server.notifier.reply_message")
def test_webhook_callback_text_message(mock_reply, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_LINE_WEBHOOK", "true")
    mock_reply.return_value = {"success": True}
    client = TestClient(app)

    payload = {
        "destination": "Uxxx",
        "events": [
            {
                "replyToken": "test-reply-token-123",
                "type": "message",
                "mode": "active",
                "timestamp": 123456789,
                "source": {
                    "type": "user",
                    "userId": "Utestuser12345",
                },
                "message": {
                    "id": "1",
                    "type": "text",
                    "text": "功能表",
                },
            }
        ],
    }

    resp = client.post("/callback", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["events_processed"] == 1

    assert mock_reply.called
    call_args = mock_reply.call_args[1]
    assert call_args["reply_token"] == "test-reply-token-123"
    assert "功能表" in call_args["text"]
    assert len(call_args["quick_replies"]) >= 6


@patch("scripts.line_webhook_server.notifier.reply_message")
def test_webhook_callback_follow_event(mock_reply, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_LINE_WEBHOOK", "true")
    mock_reply.return_value = {"success": True}
    client = TestClient(app)

    payload = {
        "destination": "Uxxx",
        "events": [
            {
                "replyToken": "welcome-token-456",
                "type": "follow",
                "mode": "active",
                "timestamp": 123456789,
                "source": {
                    "type": "user",
                    "userId": "Unewfriend999",
                },
            }
        ],
    }

    resp = client.post("/callback", json=payload)
    assert resp.status_code == 200
    assert mock_reply.called
    call_args = mock_reply.call_args[1]
    assert call_args["reply_token"] == "welcome-token-456"
    assert "歡迎加入" in call_args["text"]
