#!/usr/bin/env python3
"""Unit tests for LINE Bot FastAPI Webhook Server."""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from scripts.line_webhook_server import app


def test_webhook_root_endpoint():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert data["service"] == "sportslottery-line-bot"


@patch("scripts.line_webhook_server.notifier.reply_message")
def test_webhook_callback_text_message(mock_reply):
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
def test_webhook_callback_follow_event(mock_reply):
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
