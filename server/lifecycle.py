"""FastAPI-owned background resource lifecycle."""

from __future__ import annotations

import atexit
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.market_scheduler import get_market_scheduler, stop_market_scheduler_if_initialized

logger = logging.getLogger("server.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the in-process market scheduler once and always stop it on shutdown."""
    scheduler = get_market_scheduler()
    scheduler.start()
    logger.info("FastAPI startup: Market intelligence scheduler initiated.")
    try:
        yield
    finally:
        scheduler.stop()
        logger.info("FastAPI shutdown: Market intelligence scheduler stopped.")


atexit.register(stop_market_scheduler_if_initialized)


__all__ = ["lifespan"]
