"""Read-only presentation of source and model evidence passed by the caller."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st
from ui.metric_guide import probability_label


STATUS_TEXT = {
    "LIVE": "本次成功讀取遠端公開頁；只表示可讀，不代表找到可驗證推牌。",
    "CACHED": "使用有效期內的本機快取；不是本次即時讀取。",
    "STALE_CACHE": "遠端讀取失敗或不可用，目前僅有過期快取。",
    "PARTIAL": "部分來源或會員頁可讀，資料不完整。",
    "HTTP_403": "網站拒絕本次公開頁請求（HTTP 403），沒有可用的即時頁面證據。",
    "PARSE_EMPTY": "頁面可取得，但未解析到預期榜單或推牌資料。",
    "UNKNOWN": "沒有足夠狀態資料判斷來源是否可讀。",
    "UNAVAILABLE": "本次來源不可用；請查看各榜單的阻擋原因。",
    "FETCH_ERROR": "本次讀取發生錯誤；沒有即時來源證據。",
}
BOARD_LABELS = {
    "main_prediction": "主推榜",
    "mainPrediction": "主推榜",
    "win_rate": "勝率榜",
    "winRate": "勝率榜",
    "single_game_killer": "單場殺手榜",
    "singleGameKiller": "單場殺手榜",
}
PRECISION_LABELS = {
    "DATETIME": "精確到日期與時間",
    "DATE_ONLY": "只有日期，沒有發文時刻",
    "UNKNOWN": "發布時間未知",
    "NOT_APPLICABLE": "不適用",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _status(value: Any) -> str:
    key = str(value or "UNKNOWN").upper()
    return STATUS_TEXT.get(key, f"來源狀態：{key}（沒有更詳細的狀態說明）")


def _time(value: Any) -> str:
    if not value:
        return "未知"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return f"{text}（時區未知）"
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M %z")
    except ValueError:
        return text


def _board_labels(kinds: Any) -> str:
    if isinstance(kinds, str):
        kinds = [kinds]
    if not isinstance(kinds, (list, tuple, set)):
        return "未知"
    labels = list(dict.fromkeys(BOARD_LABELS.get(str(kind), str(kind)) for kind in kinds))
    return "、".join(labels) if labels else "未提供"


def _source_rows(expert_statuses: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group, raw in (expert_statuses or {}).items():
        if not isinstance(raw, dict):
            raw = {}
        status = raw.get("source_status", "UNKNOWN")
        candidate_count = raw.get("candidate_count", raw.get("candidate_ranker_count"))
        if candidate_count is None:
            pages = raw.get("member_pages")
            # This is the number of member pages surveyed, not the size of a ranking.
            rankers = raw.get("rankers")
            candidate_count = len(rankers) if isinstance(rankers, list) else (len(pages) if isinstance(pages, list) else "未知")
            count_label = "已巡覽會員頁數（候選發現）"
        else:
            count_label = "候選人數（榜單探索）"
        verified = raw.get("verified_pick_count", raw.get("pick_count"))
        if verified is None:
            verified = "未知"
        observed = _time(raw.get("observed_at"))
        age = raw.get("cache_age_minutes")
        cache_label = "未知" if age is None else f"{age} 分鐘"
        urls = raw.get("source_urls") or []
        if isinstance(urls, str):
            urls = [urls]
        urls_label = "、".join(str(url) for url in urls) or "未提供"
        rows.append({
            "獨立來源群組": str(group),
            "榜單／玩法": _board_labels(raw.get("board_kinds", [])),
            count_label: str(candidate_count),
            "可驗證推牌數": str(verified),
            "本次狀態": f"{status}：{_status(status)}",
            "最近觀測（UTC）": observed,
            "快取年齡": cache_label,
            "原頁 URL": urls_label,
        })
    if not rows:
        rows.append({
            "獨立來源群組": "玩運彩專家來源", "榜單／玩法": "未知",
            "已巡覽會員頁數（候選發現）": "未知", "可驗證推牌數": "未知",
            "本次狀態": f"UNKNOWN：{_status('UNKNOWN')}", "最近觀測（UTC）": "未知",
            "快取年齡": "未知", "原頁 URL": "未提供",
        })
    return rows


def _render_leg(leg: Any, index: int) -> None:
    evidence = _get(leg, "signal_evidence", {}) or {}
    event = _get(leg, "event_name") or _get(leg, "event_id") or _get(leg, "match_id") or f"第 {index} 關"
    st.markdown(f"**{event}**")
    experts = evidence.get("verified_experts") or []
    status = evidence.get("expert_source_status", "UNKNOWN")
    boards = evidence.get("expert_board_kinds", [])
    observed = evidence.get("expert_observed_at")
    precision = evidence.get("publication_time_precision", "UNKNOWN")
    st.caption(
        f"來源狀態 {status}：{_status(status)}｜榜單：{_board_labels(boards)}｜"
        f"觀測時間（UTC）：{_time(observed)}｜發布時間精度：{PRECISION_LABELS.get(str(precision), str(precision))}"
    )
    if not experts:
        st.info("本關目前沒有可驗證推牌；榜單可讀或有候選人，都不能推斷這場有人推薦或反對。")
    for expert in experts:
        if not isinstance(expert, dict):
            continue
        expert_boards = _board_labels(expert.get("board_kinds", boards))
        stamp = expert.get("pick_timestamp") or expert.get("pick_date")
        expert_precision = expert.get("publication_time_precision", precision)
        st.write(
            f"公開推薦：{expert.get('raw_pick') or '未知'}｜榜單：{expert_boards}｜"
            f"發文時間：{_time(stamp)}（{PRECISION_LABELS.get(str(expert_precision), str(expert_precision))}）｜"
            f"觀測時間：{_time(expert.get('observed_at') or observed)}"
        )
        url = expert.get("source_url")
        if url:
            st.markdown(f"原頁：[開啟公開推牌頁]({url})")
    urls = evidence.get("expert_source_urls") or []
    if isinstance(urls, str):
        urls = [urls]
    if not experts and urls:
        st.caption("可核對榜單／會員頁：" + "、".join(str(url) for url in urls))


def _render_model(model: Any, index: int) -> None:
    name = _get(model, "source_name") or _get(model, "name") or _get(model, "source_id") or f"模型 {index}"
    metadata = _get(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    status = _get(model, "probability_status") or metadata.get("probability_status", "UNKNOWN")
    method = _get(model, "market_fair_method") or metadata.get("market_fair_method", "UNKNOWN")
    probability = _get(model, "probability")
    value = probability_label(probability)
    if status == "MARKET_BASELINE_ONLY":
        status_text = "市場基準，不是模型勝率；不可解讀成模型預測。"
    elif status == "UNVALIDATED_MODEL_ESTIMATE":
        status_text = "未經實證校準的模型估計；不代表已驗證勝率。"
    else:
        status_text = f"機率狀態：{status}。"
    if status == "REFERENCE_ONLY":
        status_text = "僅供參考，時效或賽前資料不足；未進入本場模型融合。"
    method_text = {
        "COMPLETE_MARKET_PROPORTIONAL": "完整市場盤口比例去水",
        "TWO_WAY_PROPORTIONAL": "雙向盤口比例去水",
        "BREAKEVEN_BASELINE_NOT_DEVIGGED": "單一盤口打平門檻，未去水",
    }.get(str(method), f"市場公平價方法：{method}")
    interval = _get(model, "confidence_interval")
    if interval is None:
        uncertainty = "沒有實證校準區間；不提供信賴區間或保守 EV。"
    else:
        uncertainty = f"區間資料：{interval}（需另核對校準依據）。"
    st.write(f"{name}：{value}｜{status_text}｜{method_text}｜{uncertainty}")
    if _get(model, "is_loaded") is not None:
        st.caption(f"設定：{'啟用' if _get(model, 'enabled') else '停用'}｜套件載入：{'成功' if _get(model, 'is_loaded') else '未載入'}｜本次資料時效：{_get(model, 'freshness_status') or 'UNKNOWN'}｜資料截至 {_time(_get(model, 'data_as_of'))}")
    elo = metadata if _get(model, "source_id") == "live_mlb_elo" else {}
    if elo:
        source = elo.get("source") or "未知來源"
        state = "已載入官方賽果評分狀態" if elo.get("data_as_of") else "沒有賽果狀態，使用 neutral 1500 初始化"
        count = elo.get("processed_game_count", "未知")
        st.caption(
            f"MLB Elo：{state}｜來源 {source}｜資料截至 {_time(elo.get('data_as_of'))}｜"
            f"處理賽事數 {count}｜本次更新 {_time(elo.get('last_update'))}｜"
            f"投手調整 {'已使用' if elo.get('starting_pitcher_adjustment_used') else '未使用'}｜"
            f"休息日調整 {'已使用' if elo.get('rest_adjustment_used') else '未使用'}"
        )
    provenance = metadata.get("provenance") or {}
    if provenance.get("point_in_time_status") or provenance.get("pit_status"):
        pit = provenance.get("point_in_time_status", provenance.get("pit_status"))
        st.caption(f"訓練資料 PIT 狀態：{pit}｜資料截止 {_time(provenance.get('cutoff') or provenance.get('latest_match_date'))}")


def render_source_overview(expert_statuses: dict, legs: list, model_summary: list) -> None:
    """Render current source evidence passed by the caller; performs no I/O."""
    st.header("本次來源與模型證據")
    st.caption("本總覽只呈現呼叫端傳入的觀測，不會連網或讀取／修改本機資料。榜單用於候選發現；只有逐筆配對成功的公開推牌才計入可驗證推牌。")
    st.subheader("本次可核對來源、快取與阻擋狀態")
    candidates = set()
    for raw in (expert_statuses or {}).values():
        if not isinstance(raw, dict):
            continue
        for member in raw.get("member_pages", []) or []:
            if isinstance(member, dict):
                identity = member.get("member_id") or member.get("source_url") or member.get("nickname")
                if identity:
                    candidates.add(str(identity).rstrip("/"))
        for ranker in raw.get("rankers", []) or []:
            if isinstance(ranker, dict):
                identity = ranker.get("user_id") or ranker.get("member_id") or ranker.get("source_url") or ranker.get("nickname")
                if identity:
                    candidates.add(str(identity).rstrip("/"))
    unique_picks = set()
    for leg in legs or []:
        evidence = _get(leg, "signal_evidence", {}) or {}
        event_id = _get(leg, "event_id") or _get(leg, "match_id") or _get(leg, "event_name")
        for expert in evidence.get("verified_experts", []) or []:
            if isinstance(expert, dict):
                identity = (expert.get("user_id") or expert.get("nickname"), expert.get("raw_pick"),
                            expert.get("pick_timestamp") or expert.get("pick_date"), event_id)
                if identity[0] and identity[1]:
                    unique_picks.add(identity)
    st.write(f"榜單候選探索：{len(candidates) if candidates else '未知'} 位可識別候選人｜本次關卡可驗證推牌：{len(unique_picks)} 筆。")
    if candidates:
        st.caption("候選人按會員 ID／公開頁去重；同人跨榜只計一次。")
    st.caption("可驗證推牌按人、原始推牌、發布時間與賽事去重；未帶身份或原始推牌的紀錄不擴大計數。")
    st.table(_source_rows(expert_statuses))
    for group, raw in (expert_statuses or {}).items():
        raw = raw if isinstance(raw, dict) else {}
        status = raw.get("source_status", "UNKNOWN")
        st.write(f"{group}：{status} — {_status(status)}")
        for board in raw.get("board_sources", []) or []:
            if isinstance(board, dict):
                board_status = board.get("source_status", "UNKNOWN")
                board_url = str(board.get("source_url") or "")
                inferred_kind = "main_prediction" if "mainPrediction" in board_url else "win_rate" if "winRate" in board_url else board.get("board_kind", "榜單")
                board_name = _board_labels([inferred_kind])
                reason = board.get("failure_status")
                st.caption(f"{board_name}：{board_status} — {_status(board_status)}" + (f"｜阻擋原因：{reason}" if reason else "") + (f"｜{board_url}" if board_url else ""))
    st.caption("主推榜與勝率榜是同一個玩運彩來源群組；同一會員跨榜出現只算一個候選人，不算兩個獨立來源。候選數與可驗證推牌數分開列示。")
    st.subheader("各關卡推牌證據")
    if not legs:
        st.info("沒有傳入本次關卡資料；無法判定是否存在公開推牌。")
    else:
        for index, leg in enumerate(legs, start=1):
            with st.expander(str(_get(leg, "event_name") or _get(leg, "event_id") or f"第 {index} 關"), expanded=False):
                _render_leg(leg, index)
    st.subheader("機率方法與資料時效")
    if not model_summary:
        st.info("沒有傳入本次模型摘要。")
    else:
        for index, model in enumerate(model_summary, start=1):
            _render_model(model, index)
