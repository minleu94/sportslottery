"""User-facing labels for exact-scope model qualification."""

LABELS = {
    "ACCEPTED": "通過目前範圍驗收",
    "REJECTED": "未通過市場基準驗收",
    "NOT_EVALUATED": "尚未驗收",
    "INSUFFICIENT_EVIDENCE": "前瞻樣本不足",
    "INSUFFICIENT_EVALUATION": "可比較樣本不足",
    "INSUFFICIENT_CLUSTERS": "獨立事件群不足",
    "HISTORICAL_ONLY": "僅外部歷史回測",
    "INVALID_CHRONOLOGY": "資料時序未通過",
    "CALIBRATION_UNAVAILABLE": "校準資料不足",
}


def acceptance_label(status):
    return LABELS.get(status, "未完成本場範圍驗收")


def acceptance_rows(legs):
    rows = {}
    for leg in legs:
        data = leg if isinstance(leg, dict) else leg.to_dict()
        for model in (data.get("signal_evidence") or {}).get("model_acceptance_statuses", []):
            key = (model.get("model_id"), data.get("league"), data.get("market"), model.get("status"))
            rows[key] = {"模型": key[0], "聯賽": key[1], "玩法": key[2], "驗收狀態": acceptance_label(key[3])}
    return list(rows.values())
