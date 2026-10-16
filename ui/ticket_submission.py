"""Stable UI submissions and an explicit report of snapshot failures."""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from typing import Any

from core.bet_validation import assess_leg, validate_recommendation_legs
from integrations.common.models import PredictionSignal, TaiwanLeg


def recommendation_fingerprint(item: dict, stake: float, placed_odds: float) -> str:
    identity_fields = ("canonical_event_id", "event_id", "sport", "league", "start_time_utc",
                       "market", "market_type", "side", "line", "selection")
    payload = {"legs": [{key: leg.get(key) for key in identity_fields} for leg in item["legs"]],
               "stake": round(stake, 2), "placed_odds": round(placed_odds, 2)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def readiness(item: dict) -> dict:
    checks = [assess_leg(leg) for leg in item.get("legs", [])]
    messages = list(dict.fromkeys(message for check in checks for message in check["messages"]))
    try:
        validate_recommendation_legs(item.get("legs", []))
    except ValueError as exc:
        if not messages:
            messages.append(str(exc))
    return {"is_ready": bool(checks) and not messages, "messages": messages}


def _snapshot_leg(raw: dict[str, Any]) -> TaiwanLeg:
    """Keep all dataclass evidence when restoring a persisted recommendation."""
    allowed = {field.name for field in fields(TaiwanLeg)}
    payload = {key: value for key, value in raw.items() if key in allowed}
    payload["taiwan_odds"] = raw.get("taiwan_odds", raw.get("odds"))
    payload["market"] = raw.get("market", raw.get("market_type"))
    signal_fields = {field.name for field in fields(PredictionSignal)}
    payload["signals"] = [PredictionSignal(**{k: v for k, v in signal.items() if k in signal_fields})
                          if isinstance(signal, dict) else signal for signal in raw.get("signals", [])]
    return TaiwanLeg(**payload)


def record_recommendation(recorder, snapshot_logger, item: dict, stake: float,
                          placed_odds: float, submission_key: str) -> tuple[dict, list[str]]:
    """Record locally; retries use the same ledger key and never repeat a debit."""
    result = recorder.place_ticket(
        legs=item["legs"], stake=stake, total_odds=placed_odds,
        recommendation_odds=item["total_odds"], placed_odds=placed_odds,
        entry_mode="recommendation", idempotency_key=submission_key,
        notes=f"瘋狗流 {item['parlay_name']}；本機記錄已購買注單",
    )
    warnings = []
    # The full source payload is also stored in the atomic ticket transaction.
    # A retry can repair a failed research log without charging the wallet again.
    for index, raw in enumerate(result.get("legs", item["legs"]), 1):
        try:
            snapshot_logger.log_snapshot(_snapshot_leg(raw))
        except Exception as exc:
            warnings.append(f"第 {index} 關研究快照未寫入：{exc}")
    return result, warnings
