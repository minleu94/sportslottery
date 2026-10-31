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
import os
import sys
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from core.line_notifier import LineNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("line_webhook")

app = FastAPI(title="Sportslottery LINE Bot Webhook")
notifier = LineNotifier()

# Mount static folder for serving QR code PNGs
(ROOT_DIR / "static" / "qr").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")


def verify_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Validate X-Line-Signature against channel secret."""
    if not secret or not signature:
        return False
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
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(None),
):
    """Webhook callback endpoint for LINE Messaging API."""
    body_bytes = await request.body()

    # Enforce mandatory cryptographic signature verification
    secret = str(notifier.config.get("channel_secret") or "").strip()
    is_test_mode = os.environ.get("ALLOW_INSECURE_LINE_WEBHOOK", "").lower() in ("1", "true", "yes")

    if not is_test_mode:
        if not secret:
            logger.warning("LINE webhook rejected: channel_secret is not configured on this server.")
            raise HTTPException(
                status_code=503,
                detail="LINE webhook service unavailable: channel_secret is not configured",
            )
        if not x_line_signature or not verify_signature(body_bytes, x_line_signature, secret):
            logger.warning("Invalid LINE webhook signature rejected")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        if secret and x_line_signature and not verify_signature(body_bytes, x_line_signature, secret):
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception as exc:
        logger.error("Failed to parse LINE webhook JSON: %s", exc)
        return Response(content="Invalid JSON", status_code=400)

    events = data.get("events", [])
    logger.info("Received %d LINE webhook event(s)", len(events))
    if events:
        # LINE expects a quick 2xx acknowledgement. Command handling can involve
        # slow data searches, so run it after the response has been sent.
        background_tasks.add_task(process_events, events)
    return {"status": "ok", "events_processed": len(events)}


def process_events(events: list[Dict[str, Any]]) -> None:
    """Process accepted LINE events outside the webhook response path."""
    for ev in events:
        try:
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

                    # Process command via LineNotifier with LINE user ID for profile binding & isolation
                    full_res = notifier.handle_user_message_full(user_text, line_user_id=user_id)
                    reply_text = full_res.get("text", "")
                    image_url = full_res.get("image_url")
                    quick_replies = full_res.get("quick_replies") or notifier.default_quick_replies()

                    # Send reply with quick reply shortcut pills and optional image
                    if reply_token:
                        notifier.reply_message(
                            reply_token=reply_token,
                            text=reply_text,
                            quick_replies=quick_replies,
                            image_url=image_url,
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
        except Exception:
            logger.exception("Failed to process LINE webhook event type=%r", ev.get("type"))


if __name__ == "__main__":
    # Keep the historical command as an alias for the unified service manager.
    # Running an isolated webhook would leave the React UI and tunnel out of sync.
    from scripts.tray_manager import AppTrayManager
    raise SystemExit(AppTrayManager().run())
