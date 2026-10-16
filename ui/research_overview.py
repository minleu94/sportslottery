"""Read-only operational overview and legacy reference counts."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from core.research_paths import PROJECT_ROOT, research_paths


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows


def render_research_overview():
    paths = research_paths()
    files = sorted((paths["root"] / "runs").glob("*/run.json"), key=lambda path: path.parent.name)
    if files:
        try:
            run = json.loads(files[-1].read_text(encoding="utf-8"))
            labels = {"COMPLETE": "流程完成", "RUNNING": "執行中", "FAILED": "有步驟失敗，待恢復"}
            st.caption(f"最近背景研究：{labels.get(run.get('status'), '狀態未知')} · "
                       f"開始時間 {run.get('started_at', '未知')} · 資料窗口 {run.get('run_window_id', '未知')}。")
            if run.get("status") == "FAILED":
                failed = [name for name, stage in run.get("stages", {}).items() if stage.get("status") == "FAILED"]
                st.warning("背景流程需要恢復的步驟：" + "、".join(failed))
        except (OSError, ValueError, TypeError):
            st.warning("最近背景研究紀錄無法讀取。")
    else:
        st.caption("背景研究尚無執行紀錄；目前成績只反映已保存的有效前瞻資料。")
    previous = PROJECT_ROOT / "data/historical"
    count = len(read_jsonl(previous / "prediction_snapshots.jsonl"))
    tickets = len(read_jsonl(previous / "parlay_snapshots.jsonl"))
    st.caption(f"新前瞻資料與背景流程共用 {paths['root']}。舊單關 {count} 筆、舊串關階梯紀錄 {tickets} 筆保留在原檔作參考，未重新標成新版實驗。")
