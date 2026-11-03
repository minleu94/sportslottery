from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response

from core.line_notifier import LineNotifier

logger = logging.getLogger("server.api")
_line_notifier = LineNotifier()

router = APIRouter()
MAX_LINE_WEBHOOK_BODY_BYTES = 1024 * 1024
MAX_LINE_WEBHOOK_EVENTS = 100



@router.post("/callback")
async def line_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: Optional[str] = Header(None, alias="X-Line-Signature"),
):
    """Webhook callback endpoint for LINE Messaging API with mandatory cryptographic signature verification."""
    declared_length = request.headers.get("content-length")
    try:
        if declared_length is not None and int(declared_length) > MAX_LINE_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="LINE webhook payload is too large.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_LINE_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="LINE webhook payload is too large.")
        body.extend(chunk)
    body_bytes = bytes(body)
    secret = str(_line_notifier.config.get("channel_secret") or "").strip()
    is_test_mode = os.environ.get("ALLOW_INSECURE_LINE_WEBHOOK", "").lower() in ("1", "true", "yes")

    if not is_test_mode:
        if not secret:
            logger.warning("LINE webhook rejected: channel_secret is not configured on this server.")
            raise HTTPException(
                status_code=503,
                detail="LINE webhook service unavailable: channel_secret is not configured",
            )
        if not x_line_signature or not verify_line_signature(body_bytes, x_line_signature, secret):
            logger.warning("LINE webhook rejected: invalid or missing X-Line-Signature header.")
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
    else:
        if secret and x_line_signature and not verify_line_signature(body_bytes, x_line_signature, secret):
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
        logger.debug("LINE webhook running in test mode (ALLOW_INSECURE_LINE_WEBHOOK=true).")

    try:
        data = json.loads(body_bytes)
    except Exception:
        return Response(content="Invalid JSON", status_code=400)

    if not isinstance(data, dict) or not isinstance(data.get("events", []), list):
        return Response(content="Invalid webhook event list", status_code=400)
    events = data.get("events", [])
    if len(events) > MAX_LINE_WEBHOOK_EVENTS:
        raise HTTPException(status_code=413, detail="LINE webhook contains too many events.")
    if events:
        background_tasks.add_task(process_line_events, events)
    return {"status": "ok", "events_processed": len(events)}


def verify_line_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Validate X-Line-Signature against channel secret."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected).decode("utf-8")
    return hmac.compare_digest(expected_b64, signature)


def process_line_events(events: list[Dict[str, Any]]) -> None:
    """Process accepted LINE events asynchronously outside the webhook response path."""
    for ev in events:
        event_id = ev.get("webhookEventId")
        if event_id and not _line_notifier.claim_webhook_event(str(event_id)):
            logger.info("Ignoring duplicate LINE webhook event %s", str(event_id)[:10])
            continue
        early_reply = None
        user_id = None
        ev_type = None
        try:
            ev_type = ev.get("type")
            reply_token = ev.get("replyToken")
            source = ev.get("source", {})
            user_id = source.get("userId")

            if user_id and not _line_notifier.config.get("user_id"):
                _line_notifier.save_config({"user_id": user_id, "enabled": True})

            if ev_type == "message":
                msg = ev.get("message", {})
                if msg.get("type") == "text":
                    user_text = str(msg.get("text", "")).strip()
                    if reply_token and user_id and _line_notifier.is_slow_parlay_search_request(user_text):
                        early_reply = _line_notifier.reply_message(
                            reply_token=reply_token,
                            text="🐕 收到，正在搜尋串關組合，完成後會接著傳送結果。",
                        )
                    full_res = _line_notifier.handle_user_message_full(user_text, line_user_id=user_id)
                    reply_text = full_res.get("text", "")
                    image_url = full_res.get("image_url")
                    quick_replies = full_res.get("quick_replies") or _line_notifier.default_quick_replies()
                    if early_reply and early_reply.get("success"):
                        result = _line_notifier.send_push_message(
                            text=reply_text,
                            user_id=user_id,
                            image_url=image_url,
                            quick_replies=quick_replies,
                        )
                        if not result.get("success"):
                            logger.warning("LINE parlay result push failed for user %s: %s", user_id[:8], result.get("error"))
                    elif reply_token:
                        _line_notifier.reply_message(
                            reply_token=reply_token,
                            text=reply_text,
                            quick_replies=quick_replies,
                            image_url=image_url,
                        )

            elif ev_type == "follow":
                welcome_text = (
                    "🎉 歡迎加入【台灣運彩 瘋狗流決策助手】(v2.3.0 Dev)！\n"
                    "---------------------------\n"
                    "本官方助手能為您即時提供：\n"
                    "• 🎯 智慧串關推薦（直接輸入目標倍率，如「20倍」）\n"
                    "• 💰 每週 NT$200 風控錢包與儲備池查詢\n"
                    "• ☀️ 每日賽季開盤雷達焦點賽事\n"
                    "• 🛡️ 串關聽牌對沖保本提醒\n\n"
                    "請點選下方快捷按鈕開始體驗！🐕"
                )
                if reply_token:
                    _line_notifier.reply_message(
                        reply_token=reply_token,
                        text=welcome_text,
                        quick_replies=_line_notifier.default_quick_replies(),
                    )
        except Exception as exc:
            if early_reply and early_reply.get("success") and user_id:
                _line_notifier.send_push_message(
                    text="⚠️ 串關搜尋暫時發生問題，請稍後再試。",
                    user_id=user_id,
                    quick_replies=_line_notifier.default_quick_replies(),
                )
            logger.warning("[LINE_BOT_EVENT_ERROR] event_type=%s user_id=%s error=%s", ev_type, user_id, str(exc), exc_info=True)
