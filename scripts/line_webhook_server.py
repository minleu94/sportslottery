"""Backward-compatible alias for the unified Sportslottery API and LINE webhook."""

from __future__ import annotations

import uvicorn

from server.api import app
from server.routers.line import (
    _line_notifier as notifier,
    line_service_status as root,
    process_line_events as process_events,
    verify_line_signature as verify_signature,
)


async def callback(*args, **kwargs):
    """Compatibility import; the canonical callback is registered on ``server.api:app``."""
    from server.routers.line import line_webhook_callback
    return await line_webhook_callback(*args, **kwargs)


if __name__ == "__main__":
    uvicorn.run("server.api:app", host="127.0.0.1", port=8100, reload=False)
