#!/usr/bin/env python3
"""Experimental Sportslottery QR payload and manual ticket detail helpers.

The local ``SPORTSLOTTERY_LOCAL`` payload is not an official Taiwan Sports
Lottery encoding. No kiosk acceptance or direct-ticket compatibility has been
verified. Production UI surfaces manual ticket details only and links users to
the official betting page for current prices and submission.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any, Dict, List, Optional
import qrcode
from qrcode.image.pil import PilImage


MARKET_CODES: Dict[str, str] = {
    "不讓分": "SU",
    "獨贏": "SU",
    "讓分": "ATS",
    "大小": "OU",
    "單雙": "OE",
    "單節不讓分": "1Q_SU",
}
OFFICIAL_TAIWAN_LOTTERY_QR_SUPPORTED = False


def build_lottery_slip_payload(
    legs: List[Dict[str, Any]],
    total_stake: float,
    parlay_name: str = "",
    round_robin_spec: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a local experimental payload and manual ticket details."""
    formatted_legs = []
    for leg in legs:
        mkt = str(leg.get("market") or "")
        mkt_code = MARKET_CODES.get(mkt, "GEN")
        formatted_legs.append({
            "event_id": str(leg.get("event_id") or ""),
            "league": str(leg.get("league") or ""),
            "match": f"{leg.get('away_team')} vs {leg.get('home_team')}",
            "market": mkt,
            "market_code": mkt_code,
            "selection": str(leg.get("selection") or ""),
            "side": str(leg.get("side") or ""),
            "line": str(leg.get("line") or ""),
            "odds": float(leg.get("taiwan_odds") or leg.get("odds") or 1.0),
        })

    # This is only a Sportslottery-local QR payload, not a Taiwan Lottery protocol.
    leg_tokens = [f"{l['event_id']}:{l['market_code']}:{l['selection']}" for l in formatted_legs]
    ticket_type = round_robin_spec if round_robin_spec else f"{len(legs)}P1"
    compact_code = f"SPORTSLOTTERY_LOCAL|{int(total_stake)}|{ticket_type}|{'/'.join(leg_tokens)}"

    return {
        "format": "SPORTSLOTTERY_LOCAL_EXPERIMENTAL",
        "ticket_type": ticket_type,
        "parlay_name": parlay_name or f"{len(legs)} 串 1",
        "total_stake": total_stake,
        "legs": formatted_legs,
        "compact_code": compact_code,
    }


def generate_qr_code_data_url(content: str, box_size: int = 8, border: int = 2) -> str:
    """Generate a Base64 data URL for a PNG QR Code directly in memory."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_str = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64_str}"


def generate_qr_code_file(content: str, file_path: Path, box_size: int = 8, border: int = 2) -> Path:
    """Generate a QR code image and persist as a PNG file on disk."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img.save(str(file_path), format="PNG")
    return file_path
