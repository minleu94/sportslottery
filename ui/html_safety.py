"""Escaping helpers for trusted HTML snippets rendered by Streamlit."""

from __future__ import annotations

from html import escape
from typing import Any


def html_text(value: Any) -> str:
    """Escape an untrusted value for HTML text or a quoted attribute context."""
    return escape("" if value is None else str(value), quote=True)
