"""Operational research screens without fetching odds or changing a wallet."""
from __future__ import annotations
import streamlit as st
from core.research_health import build_research_health


def render_health_panel(data_root=None):
    if st.button("更新 Windows 排程觀測", help="只查詢研究任務，不更改排程設定。"):
        from core.research_operations import refresh_task_observation
        with st.spinner("讀取排程狀態…"):
            refresh_task_observation(data_root)
    health = build_research_health(data_root)
    pipeline = health["pipeline"]
    st.header("資料與排程健康")
    quality = health.get("data_quality", {})
    st.caption("流程狀態與資料完整度分開判讀；COMPLETE 代表工作流程完成。")
    if quality.get("status") == "NEEDS_ATTENTION":
        st.warning("資料仍有待處理項目：配對、來源或模型時效未完整。")
    for incident in health.get("alerts", []):
        st.warning(incident["message"])
    with st.expander("查看資料完整度與模型可用狀態"):
        st.json(quality)
        if health.get("notification"):
            st.json(health["notification"])
    st.caption("從保存的實際執行與來源紀錄判讀；頁面不會抓取新盤口。時間以 UTC 顯示。")
    left, right = st.columns(2)
    left.metric("最近流程狀態", pipeline["status"])
    right.metric("距最近成功（分鐘）", f"{pipeline['minutes_since_success']:.0f}" if pipeline["minutes_since_success"] is not None else "未知")
    st.caption(f"最近開始：{pipeline['last_started_at'] or '未知'}；最近完整成功：{pipeline['last_success_at'] or '未知'}。預定每 {pipeline['cadence_minutes']} 分鐘。")
    if pipeline["overdue"]:
        st.warning("超過兩個更新週期沒有完整成功紀錄；資料可能已過期。")
    if pipeline["error"]:
        st.error(pipeline["error"])
    stages = [{"步驟":key,"狀態":row.get("status"),"嘗試次數":row.get("attempts"),"原因":row.get("error","")}
              for key,row in pipeline["stages"].items()]
    if stages:
        st.dataframe(stages,hide_index=True,use_container_width=True)
    scheduler = health["scheduler"]
    if scheduler:
        st.subheader("Windows 排程觀測")
        task_labels={"Ready":"待執行","Running":"執行中","Disabled":"停用","UNKNOWN":"未知"}
        st.write(f"任務狀態：{task_labels.get(scheduler.get('state'),scheduler.get('state','未知'))}；"
                 f"已啟用：{'是' if scheduler.get('enabled') is True else '否' if scheduler.get('enabled') is False else '未知'}。")
        result=scheduler.get("last_task_result")
        st.write("上次排程執行：" + ("成功（回傳0）" if result==0 else f"未成功或尚未完成（回傳{result}）" if result is not None else "未知"))
        st.caption(f"下一次（UTC）：{scheduler.get('next_run_time_utc','未知')}；本次排程觀測：{scheduler.get('observed_at_utc','未知')}。")
        if scheduler.get("error"):
            st.warning("排程狀態無法確認：" + scheduler["error"])
        if scheduler["observation_stale"]:
            st.warning("Windows 排程觀測已過期，不能用這份舊紀錄判斷目前是否正在執行。")
    else:
        st.info("尚無 Windows 排程實際觀測；流程紀錄不等於任務已啟用。")
    st.subheader("盤口來源")
    if health["sources"]:
        st.dataframe([{"聯盟":{"1":"MLB","2":"日本職棒","3":"NBA","4":"足球","6":"中華職棒","7":"WNBA","9":"韓國職棒","93":"NFL"}.get(r["alliance_id"],r["alliance_id"]),"最後觀測狀態":r.get("source_status"),"目前時效":"已過期" if r["stale"] else "15分鐘內",
                       "觀測時間（UTC）":r.get("observed_at"),"最後成功（UTC）":r.get("last_success_at"),"失敗原因":r.get("failure_status"),"完整身份數":r.get("identity_complete_count"),
                       "來源網址":r.get("source_url")} for r in health["sources"]],hide_index=True,use_container_width=True)
    else:
        st.info("尚無來源觀測紀錄。")
    st.subheader("模型資料時效")
    if health["models"]:
        st.dataframe([{"模型":r["model"],"資料截至（UTC）":r.get("data_as_of"),"落後天數":r.get("days_behind"),
                       "資料時間狀態":r.get("watermark_status"),"已處理賽果或樣本數":r.get("processed_games",r.get("match_count")),
                       "待補賽果日期":str(r.get("pending_game_dates",[])),"暫緩更新賽果數":r.get("held_final_count"),
                       "來源":r.get("source")} for r in health["models"]],hide_index=True,use_container_width=True)
    else:
        st.info("尚無可讀模型資料。")
    st.subheader("聯賽資料串接與待補優先順序")
    st.caption("按目前可用選項數排序。模型入口已配置不代表資料足夠或通過驗收；賽果來源已接通也不保證每隊名稱都可配對。")
    if health["league_connections"]:
        st.dataframe([{"聯賽":r["league"],"來源選項數":r["option_count"],"目前可用數":r["ready_option_count"],
                       "已配置模型入口":", ".join(r["configured_model_adapters"]) or "尚未配置此聯賽模型",
                       "賽果來源":"已接通" if r["result_source_supported"] else "尚未支援",
                       "provider":r.get("result_provider"),
                       "來源覆蓋狀態":r.get("result_coverage"),
                       "證據缺口":r.get("result_evidence_gap"),
                       "核對參考":r.get("result_checked_reference")} for r in health["league_connections"]],hide_index=True,use_container_width=True)
    else:
        st.info("尚無聯賽盤口觀測可判定串接狀態。")
    st.subheader("最近一次賽果配對稽核")
    st.caption(f"資料窗口紀錄：{health['settlement'].get('run_id','尚無紀錄')}。此表呈現該次執行的配對，不代表之後尚未再結算。")
    coverage = health["settlement"].get("coverage",{})
    if coverage:
        st.dataframe([{"聯賽":key,"狀態":r.get("status"),"取得賽果數":r.get("games"),"未配對數":r.get("unmatched_snapshots"),
                       "原因":str(r.get("unmatched_reason_counts",{})),"來源錯誤":str(r.get("errors",[]))} for key,r in coverage.items()],hide_index=True,use_container_width=True)
    else:
        st.info("尚無結算稽核紀錄。")
    if health["read_errors"] or health["malformed_source_records"]:
        st.warning("部分本機紀錄無法讀取；不能視為來源正常。")
        with st.expander("查看讀取問題"):
            st.json({"errors":health["read_errors"],"malformed_source_records":health["malformed_source_records"]})
    return health


def render_clv_panel(data_root=None):
    from core.clv_reporting import load_current_clv_report
    report = load_current_clv_report(root=data_root)
    st.header("推薦價格與賽前最後觀測")
    st.caption("CLV = 推薦賠率 ÷ 賽前最後觀測賠率 − 1。固定輪詢不能證明真正官方封盤價；這裡保留觀測時間與距開賽的間隔。")
    st.caption(f"目前實驗：{report['experiment_id']}")
    summary = report["observations_within_15_minutes"]
    columns = st.columns(3)
    columns[0].metric("開賽前15分鐘內觀測數", summary.get("observation_count", 0))
    columns[1].metric("唯一選項", summary.get("unique_option_count", 0))
    columns[2].metric("唯一賽事", summary.get("unique_event_count", 0))
    value = summary.get("first_forecast_mean_odds_clv_ratio")
    st.metric("首次推薦的平均價格差", f"{value:+.2%}" if value is not None else "資料不足")
    st.caption("每個精確賽事／玩法／選項只以首次賽前推薦評分；重複輪詢仍保存為觀測，不能當作獨立賽事。")
    with st.expander("首次推薦評估口徑與賽事群組區間"):
        st.json(summary)
    if report["predictions"]:
        st.dataframe(report["predictions"],hide_index=True,use_container_width=True)
    else:
        st.info("目前實驗尚無可核對的推薦快照。不同版本的紀錄不會混入目前統計。")
    with st.expander("查看缺資料與排除統計"):
        st.json({"status_counts":report["status_counts"],"audit":report["audit"]})
    return report


def render_replay_panel(data_root=None):
    from core.clv_reporting import read_jsonl
    from core.research_paths import research_paths
    from core.experiment_identity import get_current_experiment_identity, validate_experiment_identity
    from core.recommendation_replay import replay_recommendations, compare_experiment_versions, replay_parlay_recommendations
    snapshots=read_jsonl(research_paths(data_root)["snapshots"])
    parlay_records=read_jsonl(research_paths(data_root)["parlays"])
    current=get_current_experiment_identity()["experiment_id"]
    ids=sorted({row["experiment_identity"]["experiment_id"] for row in snapshots+parlay_records
                if validate_experiment_identity(row.get("experiment_identity"))})
    ids=[current]+[value for value in ids if value!=current]
    st.header("推薦重播與版本比較")
    st.caption("使用當時封存的資料重播理由與計算，不以現在的模型改寫歷史。版本成績只比較共同、有效、已結算的相同選項。")
    def version_label(value):
        rows=[row for row in snapshots if (row.get("experiment_identity") or {}).get("experiment_id")==value]
        times=[str(row.get("snapshot_timestamp") or row.get("timestamp") or "") for row in rows]
        stamp=min(times)[:16].replace("T"," ") if times else "尚無快照"
        label="目前版本" if value==current else "歷史版本"
        return f"{label} · {stamp} UTC · {len(rows)}筆 · {value[4:12]}"
    selected=st.selectbox("選擇要重播的實驗版本",ids,format_func=version_label)
    replay=replay_recommendations(snapshots,experiment_id=selected)
    if replay["recommendations"]:
        st.dataframe([{k:r.get(k) for k in ("snapshot_id","snapshot_timestamp","event_start","market","selection","odds","probability_status","breakeven_probability","independent_support_count","integrity_valid","settlement_status")}
                      for r in replay["recommendations"]],hide_index=True,use_container_width=True)
        selected_snapshot=st.selectbox("查看完整推薦證據",[r["snapshot_id"] for r in replay["recommendations"]])
        row=next(r for r in replay["recommendations"] if r["snapshot_id"]==selected_snapshot)
        if not row["integrity_valid"]:
            st.error("快照完整性驗證失敗，不能把這筆資料當成可信的歷史推薦。")
        st.caption(f"封存勝率欄位：{row.get('probability_status','未知')}；重算 EV：{row.get('replayed_expected_value')}。")
        with st.expander("查看原始版本、模型設定與完整證據"):
            st.json(row)
    else:
        st.info("此版本尚無保存的推薦快照。")
    st.subheader("整張串關重播")
    tickets=replay_parlay_recommendations(parlay_records,experiment_id=selected)
    if tickets["recommendations"]:
        ticket_index=st.selectbox("查看封存串關",range(len(tickets["recommendations"])),
                                  format_func=lambda i:str(tickets["recommendations"][i].get("candidate_id") or f"串關 {i+1}"))
        ticket=tickets["recommendations"][ticket_index]
        if not ticket.get("integrity_valid") or not ticket.get("math_consistent") or not ticket.get("forward_validation_eligible"):
            st.warning("此票的封存或計算驗證未通過；請查看原始證據，不能用於可信成績。")
        st.caption(f"原始賠率：{ticket.get('original_total_odds',ticket.get('odds'))}；打平門檻：{ticket.get('breakeven_probability')}；重算 EV：{ticket.get('expected_value')}。")
        with st.expander("查看整張串關與每關的封存證據"):
            st.json(ticket)
    else:
        st.info("此版本尚無封存的串關候選。")
    versions=st.multiselect("比較實驗版本（至少兩個）",ids,default=ids[:2] if len(ids)>1 else [],format_func=version_label)
    if len(versions)>=2:
        comparison=compare_experiment_versions(snapshots,experiment_ids=versions)
        st.metric("共同有效已結算選項",comparison["settled_matched_count"])
        if comparison["settled_matched_count"]:
            st.json(comparison["version_metrics"])
            st.json(comparison["pairwise_deltas"])
        else:
            st.info("沒有足夠的共同已結算資料，無法判定哪個版本較好。")
        with st.expander("查看版本比較的稽核資訊"):
            st.json(comparison)
    return replay
