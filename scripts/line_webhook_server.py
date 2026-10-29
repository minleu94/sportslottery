#!/usr/bin/env python3
"""LINE Messaging API Webhook Server (FastAPI).

Receives incoming LINE webhook events, processes interactive user commands
(e.g., "20倍", "查戰績", "今日開盤", "對沖", "功能表"), and sends immediate
reply messages with Quick Reply action buttons.
"""

from __future__ import annotations

import hmac
import hashlib
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.line_notifier import LineNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("line_webhook")

app = FastAPI(title="Sportslottery LINE Bot Webhook")
notifier = LineNotifier()


def verify_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Validate X-Line-Signature against channel secret."""
    if not secret:
        return True
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    import base64
    expected_b64 = base64.b64encode(expected).decode("utf-8")
    return hmac.compare_digest(expected_b64, signature)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "online",
        "service": "sportslottery-line-bot",
        "configured": notifier.is_configured(),
    }


@app.post("/callback")
async def callback(
    request: Request,
    x_line_signature: str = Header(None),
):
    """Webhook callback endpoint for LINE Messaging API."""
    body_bytes = await request.body()

    # Optional signature check if channel_secret is specified in config
    secret = notifier.config.get("channel_secret")
    if secret and x_line_signature:
        if not verify_signature(body_bytes, x_line_signature, secret):
            logger.warning("Invalid LINE webhook signature rejected")
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception as exc:
        logger.error("Failed to parse LINE webhook JSON: %s", exc)
        return Response(content="Invalid JSON", status_code=400)

    events = data.get("events", [])
    logger.info("Received %d LINE webhook event(s)", len(events))

    for ev in events:
        ev_type = ev.get("type")
        reply_token = ev.get("replyToken")
        source = ev.get("source", {})
        user_id = source.get("userId")

        # Automatically store user_id into config if missing so push alerts reach this user
        if user_id and not notifier.config.get("user_id"):
            logger.info("Discovered and saved new user ID: %s", user_id[:8] + "...")
            notifier.save_config({"user_id": user_id, "enabled": True})

        if ev_type == "message":
            msg = ev.get("message", {})
            if msg.get("type") == "text":
                user_text = str(msg.get("text", "")).strip()
                logger.info("Inbound user message from %s: %s", (user_id or "unknown")[:6], user_text)

                # Process command via LineNotifier
                reply_text = notifier.handle_user_message(user_text)

                # Send reply with quick reply shortcut pills
                if reply_token:
                    notifier.reply_message(
                        reply_token=reply_token,
                        text=reply_text,
                        quick_replies=notifier.default_quick_replies(),
                    )

        elif ev_type == "follow":
            logger.info("New user added bot as friend: %s", (user_id or "unknown")[:6])
            welcome_text = (
                "🎉 歡迎加入【台灣運彩 瘋狗流決策助手】！\n"
                "---------------------------\n"
                "本官方助手能為您即時提供：\n"
                "• 🎯 智慧串關推薦（直接輸入目標倍率，如「20倍」）\n"
                "• 💰 每週 NT$200 風控錢包與儲備池查詢\n"
                "• ☀️ 每日賽季開盤雷達焦點賽事\n"
                "• 🛡️ 串關聽牌對沖保本提醒\n\n"
                "請點選下方快捷按鈕開始體驗！🐕"
            )
            if reply_token:
                notifier.reply_message(
                    reply_token=reply_token,
                    text=welcome_text,
                    quick_replies=notifier.default_quick_replies(),
                )

    return {"status": "ok", "events_processed": len(events)}


if __name__ == "__main__":
    port = 8000
    print(f"Starting LINE Bot Webhook Server on http://127.0.0.1:{port}")
    uvicorn.run("scripts.line_webhook_server:app", host="0.0.0.0", port=port, reload=False)
