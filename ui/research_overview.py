"""Read-only operational overview, shadow forward pipeline monitor, and manual recovery."""
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
    """Render shadow forward pipeline status, health diagnostics, and recovery controls."""
    paths = research_paths()
    files = sorted((paths["root"] / "runs").glob("*/run.json"), key=lambda path: path.parent.name)

    if files:
        try:
            run = json.loads(files[-1].read_text(encoding="utf-8"))
            status = run.get("status", "UNKNOWN")
            stages = run.get("stages", {})
            window_id = run.get("run_window_id", "未知")
            started_at = run.get("started_at", "未知")

            labels = {
                "COMPLETE": "✅ 流程完成（健康運行）",
                "RUNNING": "⏳ 背景執行中",
                "FAILED": "⚠️ 待恢復 / 賽果來源重試中",
            }
            st.caption(
                f"最近背景研究狀態：**{labels.get(status, status)}** · "
                f"資料窗口：`{window_id}` · 開始時間：{started_at}。"
            )

            if status == "FAILED":
                failed = [name for name, stage in stages.items() if stage.get("status") == "FAILED"]
                st.warning(
                    f"**背景流程需要恢復的步驟：** {'、'.join(failed)}\n\n"
                    "💡 **前瞻機制說明**：\n"
                    "瘋狗流「影子前瞻系統」每 15 分鐘全自動巡檢一次賽程與即時比分。\n"
                    "若比分來源（如 MLB、ESPN、CPBL）暫時遇到外部網路波動或比分延遲，系統採取**嚴格閉合防護 (Fail-Closed Integrity)**，"
                    "不以未經查證的推論結算，確保前瞻樣本統計數據的絕對純淨。\n"
                    "此狀態將在下一個 15 分鐘排程週期自動重試；您亦可隨時點擊下方按鈕手動重試。"
                )
                col_btn, _ = st.columns([2, 3])
                with col_btn:
                    if st.button("🔄 立即重試 / 恢復前瞻研究管線", key="retry_pipeline_btn", type="primary"):
                        with st.spinner("正在嘗試連線賽果並恢復前瞻流程..."):
                            try:
                                from core.research_pipeline import ResearchPipeline
                                pipeline = ResearchPipeline()
                                res = pipeline.run(resume=True)
                                if res.get("status") == "COMPLETE":
                                    st.success("🎉 前瞻研究流程已順利恢復並完成最新結算！")
                                else:
                                    st.info(f"前瞻管線已執行，目前狀態：{res.get('status')}。")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"恢復執行回報：{exc}（外部來源若暫時無法連線，系統將於背景自動重試）")
            elif status == "RUNNING":
                st.info("ℹ️ 前瞻管線正在進行新一輪賽事推論與賠率觀測，請稍候片刻。")
        except (OSError, ValueError, TypeError):
            st.warning("最近背景研究紀錄無法讀取。")
    else:
        st.caption("背景研究尚無執行紀錄；目前成績只反映已保存的有效前瞻資料。")

    previous = PROJECT_ROOT / "data/historical"
    count = len(read_jsonl(previous / "prediction_snapshots.jsonl"))
    tickets = len(read_jsonl(previous / "parlay_snapshots.jsonl"))
    st.caption(
        f"新前瞻資料與背景流程共用 `{paths['root']}`。舊單關 {count} 筆、舊串關階梯紀錄 {tickets} 筆保留在原檔作參考，未重新標成新版實驗。"
    )
