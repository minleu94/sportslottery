"""Plain-language metric education, with read-only local source evidence."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st
from core.research_paths import research_paths

ROOT_DIR = Path(__file__).resolve().parents[1]


def probability_label(value: Any) -> str:
    if isinstance(value, (float, int)) and math.isfinite(value) and 0 <= value <= 1:
        return f"{value * 100:.1f}%"
    return "未知"


def render_leg_source_evidence(leg: dict[str, Any]) -> None:
    evidence = leg.get("signal_evidence") or {}
    st.markdown("**可核對的資料來源**")
    if evidence.get("source_url"):
        st.link_button("查看此聯賽的盤口與投票原頁", evidence["source_url"])
    st.caption("盤口來自玩運彩第三方頁面，並未逐筆核對官方接受價格。")
    experts = evidence.get("verified_experts", [])
    source_status = evidence.get("expert_source_status", "UNKNOWN")
    st.caption(
        f"專家來源狀態：{source_status}｜榜單候選種類：{', '.join(evidence.get('expert_board_kinds') or []) or '未知'}｜"
        f"最近觀測：{_time_label(evidence.get('expert_observed_at'))}｜"
        f"發布時間精度：{evidence.get('publication_time_precision') or 'UNKNOWN'}"
    )
    for expert in experts:
        st.write(
            f"公開推薦：{expert.get('raw_pick') or '未知'}｜榜單：{', '.join(expert.get('board_kinds') or evidence.get('expert_board_kinds') or []) or '未知'}｜"
            f"歷史榜單紀錄：{expert.get('wins', '未知')} 勝 / {expert.get('losses', '未知')} 敗｜"
            f"歷史榜單勝率：{expert.get('win_percentage', '未知')}%（不是本場機率）"
        )
        stamp = expert.get("pick_timestamp")
        published = _time_label(stamp) if stamp and stamp != "TIMESTAMP_UNKNOWN" else "未知（只有日期或未提供時間）"
        st.caption(f"發布日期：{expert.get('pick_date') or '未知'}｜發布時間：{published}｜發布精度：{expert.get('publication_time_precision') or evidence.get('publication_time_precision') or 'UNKNOWN'}｜觀測時間：{_time_label(expert.get('observed_at') or evidence.get('expert_observed_at'))}")
        if expert.get("source_url"):
            st.link_button(f"核對 {expert.get('nickname') or '專家'} 的公開預測頁", expert["source_url"])
    if not experts:
        st.caption("此關卡目前沒有可驗證的公開推牌；榜單候選或來源可讀不代表專家已對本場推薦，也不能推斷其反對。")
    st.caption("專家榜單勝率是網站記錄的歷史表現，不是這場比賽的命中率；來源發布時間未知時，不能確認它在開賽前發布。")

    for signal in leg.get("signals", []):
        if not isinstance(signal, dict) or signal.get("source_type") != "MODEL":
            continue
        metadata = signal.get("metadata") or {}
        provenance = metadata.get("provenance") or {}
        if signal.get("source_id") == "live_mlb_elo":
            state = "已載入賽果評分狀態" if metadata.get("data_as_of") else "沒有賽果狀態，使用 neutral 1500 初始化"
            st.info(
                f"MLB Elo：{state}；來源 {metadata.get('source') or '未知'}，"
                f"處理賽事數 {metadata.get('processed_game_count', '未知')}，"
                f"最近更新 {_time_label(metadata.get('last_update'))}。"
                f"本次投手調整{'已使用' if metadata.get('starting_pitcher_adjustment_used') else '未使用'}，"
                f"休息日調整{'已使用' if metadata.get('rest_adjustment_used') else '未使用'}。"
            )
        probability_status = metadata.get("probability_status", "UNKNOWN")
        fair_method = metadata.get("market_fair_method", "UNKNOWN")
        if probability_status == "MARKET_BASELINE_ONLY":
            st.caption("以下機率是市場打平基準，不是模型勝率。")
        elif probability_status == "UNVALIDATED_MODEL_ESTIMATE":
            st.caption("以下是未經實證校準的模型估計；沒有可用的信賴區間或保守 EV。")
        st.caption(f"機率狀態：{probability_status}｜市場方法：{fair_method}。缺少完整同場同玩法盤口時，不能完成去水。")
        st.write(
            f"模型：{signal.get('source_name') or '未知'}｜資料截止："
            f"{signal.get('data_as_of') or provenance.get('latest_match_date') or '未知'}｜"
            f"本場機率估計：{probability_label(signal.get('probability'))}"
        )
        if provenance:
            st.caption(f"訓練資料：{provenance.get('dataset_source') or '未知'}｜場數：{provenance.get('match_count', '未知')}｜資料時效：{provenance.get('freshness_status') or '未知'}")
        source_url = provenance.get("dataset_url") or metadata.get("github_repo")
        if source_url:
            st.link_button(f"查看 {signal.get('source_name') or '模型'} 的資料／方法來源", source_url)


def calculate_example(odds: float, probability: float, stake: float) -> dict[str, float]:
    """Binary win/loss illustration; decimal payout includes the original stake."""
    if not all(math.isfinite(value) for value in (odds, probability, stake)):
        raise ValueError("試算數字必須是有限數值。")
    if odds <= 1 or not 0 <= probability <= 1 or stake <= 0:
        raise ValueError("賠率須大於 1、勝率須介於 0～100%，注金須大於 0。")
    ev = probability * odds - 1
    return {
        "breakeven": 1 / odds,
        "gross_payout": stake * odds,
        "win_profit": stake * (odds - 1),
        "expected_profit": stake * ev,
        "ev": ev,
        "edge_pp": (probability - 1 / odds) * 100,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return content if isinstance(content, dict) else {}
    except (OSError, ValueError):
        return {}


def _time_label(timestamp: Any) -> str:
    if not timestamp:
        return "未知"
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return "未知（時間缺少時區）"
        return parsed.strftime("%Y-%m-%d %H:%M %z")
    except ValueError:
        return "未知（時間格式無法辨識）"


def local_source_evidence(root: Path | None = None) -> list[dict[str, Any]]:
    """Read current research sources from the configured shared research root."""
    supplied_root = Path(root) if root is not None else ROOT_DIR
    data_root = research_paths(None if supplied_root.resolve() == ROOT_DIR.resolve() else supplied_root)["root"]
    rows = []
    for name, file_name, field in [
        ("MLB 盤口與投票", "scale_1.json", "matches"),
        ("MLB 專家排行榜", "experts_main_prediction_1.json", "rankers"),
    ]:
        cache_dir = "playsport_experts" if name == "MLB 專家排行榜" else "playsport"
        path = data_root / "cache" / cache_dir / file_name
        data = _read_json(path)
        observed = data.get("cached_iso")
        age_label = "未知"
        if observed:
            try:
                parsed = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    age_minutes = (datetime.now(timezone.utc) - parsed).total_seconds() / 60
                    age_label = "時間異常（紀錄在未來）" if age_minutes < 0 else (
                        "15 分鐘內的本機快取" if age_minutes <= 15 else "舊快取（超過 15 分鐘）"
                    )
            except ValueError:
                pass
        records = data.get(field)
        count = len(records) if isinstance(records, list) else 0
        rows.append({
            "來源": name, "本機紀錄數": count,
            "最近記錄時間": _time_label(observed),
            "目前可確認的狀態": age_label if count else "沒有可讀的本機資料",
            "本機路徑": str(path),
        })

    soccer_path = data_root / "cache" / "models" / "penaltyblog_dixon_coles" / "real_matches_eng.1.json"
    soccer = _read_json(soccer_path)
    matches = soccer.get("matches", [])
    matches = matches if isinstance(matches, list) else []
    dates = [str(m.get("date")) for m in matches if isinstance(m, dict) and m.get("date")]
    rows.append({
        "來源": "目前研究快取：足球歷史比分（英超）", "本機紀錄數": len(matches),
        "最近記錄時間": max(dates) if dates else "未知",
        "目前可確認的狀態": "本機訓練資料；時效需按預測日期判斷" if matches else "沒有可讀的訓練資料",
        "本機路徑": str(soccer_path),
    })
    elo_path = data_root / "model_state" / "live_mlb_elo.json"
    elo = _read_json(elo_path)
    history = elo.get("history", [])
    history = history if isinstance(history, list) else []
    elo_dates = [str(row.get("date")) for row in history if isinstance(row, dict) and row.get("date")]
    rows.append({
        "來源": "目前研究狀態：MLB Elo 評分", "本機紀錄數": len(history),
        "最近記錄時間": elo.get("data_as_of") or (max(elo_dates) if elo_dates else "未知"),
        "目前可確認的狀態": (f"已載入官方賽果狀態；{len(elo.get('processed_game_pks', []))} 場已處理，來源 {elo.get('source') or '未知'}"
                            if elo.get("ratings") and elo.get("data_as_of") else "未找到有效研究狀態；使用預設評分"),
        "本機路徑": str(elo_path),
    })

    # Keep older production-era files visible only as historical references.
    legacy_sources = [
        ("舊版留存：英超訓練資料（歷史參考）", ROOT_DIR / "data" / "cache" / "real_matches_eng.1.json", "matches"),
        ("舊版留存：MLB Elo 狀態（歷史參考）", ROOT_DIR / "data" / "live_mlb_elo_state.json", "history"),
    ]
    for label, path, field in legacy_sources:
        if not path.exists():
            continue
        legacy = _read_json(path)
        values = legacy.get(field, [])
        values = values if isinstance(values, list) else []
        legacy_dates = [str(item.get("date")) for item in values if isinstance(item, dict) and item.get("date")]
        rows.append({
            "來源": label,
            "本機紀錄數": len(values),
            "最近記錄時間": legacy.get("data_as_of") or (max(legacy_dates) if legacy_dates else "未知"),
            "目前可確認的狀態": "舊版留存資料；不代表目前研究模型的輸入或狀態",
            "本機路徑": str(path),
        })
    return rows


def render_metric_guide(root: Path = ROOT_DIR) -> None:
    st.title("看懂賠率、勝率與資料來源")
    st.write("先分清楚三件事：賠率決定贏了領多少，估計勝率描述模型的判斷，EV 比較兩者是否划算。")
    st.info("賠率換算的是打平所需命中率。模型估計、大神歷史勝率與社群支持率，都是不同的數字。")

    st.header("1. 用一張注單看懂 EV")
    st.caption("這是教學試算，不會建立注單或動用錢包。先假設結果只有贏或輸，沒有退盤或走盤。")
    odds = st.number_input("賠率（含本金的派彩倍數）", min_value=1.01, max_value=5000.0, value=2.0, step=0.1, key="guide_odds")
    probability_pct = st.slider("假設命中率（自行設定，不是系統保證）", min_value=0, max_value=100, value=60, step=1, key="guide_probability")
    stake = st.number_input("每次注金（NT$）", min_value=1.0, max_value=10000.0, value=20.0, step=1.0, key="guide_stake")
    result = calculate_example(odds, probability_pct / 100, stake)
    col1, col2 = st.columns(2)
    col1.metric("打平所需命中率", f"{result['breakeven'] * 100:.2f}%", help="1 ÷ 賠率。例如 2 倍需命中 50% 才打平。")
    col2.metric("假設條件下的 EV", f"{result['ev'] * 100:+.2f}%", help="EV = 假設命中率 × 賠率 − 1。+20% 代表每下注 1 元，長期平均淨利估計 0.2 元。")
    st.write(
        f"贏一次領回 **NT\\$ {result['gross_payout']:.2f}（含本金）**，淨賺 **NT\\$ {result['win_profit']:.2f}**；"
        f"輸一次損失 **NT\\$ {stake:.2f}**。依你設定的 {probability_pct}% 命中率，"
        f"每次平均淨損益估計為 **NT\\$ {result['expected_profit']:+.2f}**。"
    )
    st.code(f"EV = {probability_pct / 100:.2f} × {odds:.2f} − 1 = {result['ev'] * 100:+.2f}%", language=None)
    st.caption("長期平均不是每次都賺這個金額；真正命中率若比假設低，正 EV 也可能變成負 EV。")
    st.table([
        {
            "假設情境": label,
            "命中率": f"{p * 100:.1f}%",
            "EV": f"{(p * odds - 1) * 100:+.1f}%",
            "每次平均淨損益": f"NT$ {stake * (p * odds - 1):+.2f}",
        }
        for label, p in [
            ("估計偏高：實際少 10 個百分點", max(0, probability_pct / 100 - 0.1)),
            ("目前假設", probability_pct / 100),
            ("實際多 10 個百分點", min(1, probability_pct / 100 + 0.1)),
        ]
    ])

    st.header("2. 賠率與打平門檻對照")
    st.write("賠率越高，贏時派彩越大，打平門檻也越低；光看倍數，無法知道實際命中機率。")
    st.table([
        {"賠率": f"{value:g} 倍", "打平所需命中率（非預測）": f"{100 / value:.2f}%", "下注 20 元全過領回（含本金）": f"NT$ {20 * value:,.0f}"}
        for value in [1.25, 1.5, 2, 3, 5, 10, 25, 50, 100, 500]
    ])
    st.caption("例如 100 倍需長期命中 1% 才打平；這句話不代表這張單有 1% 的實際命中率。")

    st.header("3. 畫面上的分析指標代表什麼")
    st.table([
        {"指標": "隱含機率／打平門檻", "白話解釋": "1 ÷ 賠率；含莊家利潤，不能直接當真實勝率。", "例子": "2 倍 → 50%"},
        {"指標": "模型估計命中率", "白話解釋": "系統以模型與情報計算的估計；需要歷史驗證與校準。", "例子": "估計 60% 不代表 10 場一定中 6 場"},
        {"指標": "EV（預期淨報酬）", "白話解釋": "估計命中率 × 賠率 − 1；不是命中率。", "例子": "60% × 2 − 1 = +20%"},
        {"指標": "Edge／Delta（百分點）", "白話解釋": "估計命中率減去打平門檻；與 EV 的百分比不同。", "例子": "60% − 50% = +10 個百分點"},
        {"指標": "HIGH／MED／LOW", "白話解釋": "情報支持程度；不是固定的勝率級距。", "例子": "HIGH 不能換算成 80% 勝率"},
        {"指標": "串關估計命中率", "白話解釋": "全部關卡都過的機率估計；必須考慮關卡相關性。", "例子": "4 關各 60%，獨立假設下約 12.96%"},
        {"指標": "相關性折扣", "白話解釋": "目前按同隊、同時段等規則減少聯合機率，是啟發式估計。", "例子": "相關風險較高時，估計值會調低"},
        {"指標": "信賴區間／保守 EV", "白話解釋": "只有實證校準後才提供；目前未校準時留空，不用假設樣本數製造區間。", "例子": "欄位空白代表沒有足夠驗證資料"},
        {"指標": "市場基準機率", "白話解釋": "由盤口換算的基準；只有完整同場同玩法市場才可按比例去水。單一價格只代表打平門檻。", "例子": "不能當成模型勝率或已驗證勝率"},
        {"指標": "國際去水公允勝率", "白話解釋": "以 Pinnacle/Sharp 等權威盤或完整對開盤口，扣除莊家抽水後計算的無偏公允勝率。", "例子": "台彩 1.75/1.75 去水後兩端公允各 50%"},
        {"指標": "實質正期望值 (+EV)", "白話解釋": "去水公允勝率 × 賠率 − 1 > 0；代表該選項即使扣除台彩高額抽水後仍具有統計優勢。", "例子": "+EV 5% 代表每注 100 元長期理論回收 105 元"},
        {"指標": "NBA Elo & Four Factors", "白話解釋": "整合主場優勢 (+100 Elo)、勝分差 (MOV) 與四要素之 NBA 量化評分引擎。", "例子": "計算讓分覆蓋常態 CDF 與大小分預期"},
        {"指標": "ROI（已發生的報酬率）", "白話解釋": "已結算淨損益 ÷ 下注金額，與預測 EV 不同。", "例子": "總下注 200、總派彩 180 → −10%"},
        {"指標": "CLV（與收盤價比較）", "白話解釋": "下注賠率 ÷ 收盤賠率 − 1；需同場、同玩法、同讓分線。", "例子": "下注 2.0、收盤 1.8 → +11.1%；不保證中獎"},
        {"指標": "Brier／Log loss", "白話解釋": "檢查預測機率與實際結果的誤差；越低越好，需同一批資料比較。", "例子": "要與市場基準比較，不能只看單一分數"},
        {"指標": "樣本數 N", "白話解釋": "實際完成結算的觀測數；筆數達門檻仍不保證策略有效。", "例子": "1 筆中獎，不能證明長期有優勢"},
    ])

    with st.expander("串關與玩法：不讓分、讓分、大小、和局", expanded=False):
        st.write("不讓分：選擇勝方。讓分：先套用指定的加減分再判定，例如 −1.5 的一方需贏超過 1.5 分。大小：比較總得分與指定門檻。足球和局是獨立選項，不能省略。")
        st.write("串關總賠率通常將各關賠率相乘，例如 2 × 2 × 2 × 2 = 16 倍。每關 60% 且互相獨立時，全過估計為 0.6⁴ = 12.96%；同隊或同場等相關事件不能直接套用獨立假設。")
        st.write("取消、延期、退盤與走盤可能改變有效賠率和派彩，以上試算沒有涵蓋這些情況。實際結算以該注單適用的官方規則為準。")
        st.link_button("查看台灣運彩官方網站", "https://www.sportslottery.com.tw/")

    st.header("4. 大神、盤口與模型：資料從哪裡來")
    st.table([
        {"畫面資料": "盤口與賠率", "取得方式": "讀取玩運彩「運彩盤」公開頁／本機快取", "能代表什麼": "第三方頁面記錄的賠率；未逐筆與官方接受價格核對"},
        {"畫面資料": "大神推薦", "取得方式": "排行榜＋專家個人公開預測頁，配對球隊、玩法和讓分線", "能代表什麼": "有抓到該選項的公開推薦；歷史勝率不是本場命中率，發布時間仍可能未知"},
        {"畫面資料": "社群支持率", "取得方式": "玩運彩預測比例與人數", "能代表什麼": "多少人選這邊；70% 支持不代表 70% 會贏"},
        {"畫面資料": "足球模型", "取得方式": "Penaltyblog 引擎＋本機歷史比分資料", "能代表什麼": "由資料推算的機率；不是外部網站提供的現成預言"},
        {"畫面資料": "NBA Elo 模型", "取得方式": "動態 Elo 評分庫＋四要素框架＋本機狀態保存", "能代表什麼": "量化計算之 NBA 不讓分、讓分與大小分公允勝率"},
        {"畫面資料": "MLB Elo 模型", "取得方式": "本機 Elo 評分；依本次 metadata 顯示官方賽果狀態、資料日期與處理場數", "能代表什麼": "沒有 state 時從 neutral 1500 開始；目前不使用投手與休息日調整"},
        {"畫面資料": "國際權威基準盤 (+EV 標籤)", "取得方式": "Pinnacle / Sharp Consensus 盤口或完整兩面盤去水", "能代表什麼": "市場公允基準線；識別台彩高水錢陷阱或錯盤價值注單"},
        {"畫面資料": "EV／Edge／串關命中率", "取得方式": "專案自行計算", "能代表什麼": "依輸入與假設得出的估計；不是抓來的真實勝率"},
    ])
    st.write("公開資料有來源，也可能解析錯誤、配錯賽事、資料過期或暫時取不到。來源存在、資料新鮮、預測準確，是三件分開檢查的事。")
    col_sources1, col_sources2 = st.columns(2)
    col_sources1.link_button("核對玩運彩盤口與投票", "https://www.playsport.cc/predict/scale?allianceid=1")
    col_sources2.link_button("核對玩運彩主推榜", "https://www.playsport.cc/billboard/mainPrediction?allianceid=1")
    st.subheader("目前本機保存的來源紀錄")
    st.caption("這張表只讀共用研究資料根目錄中的本機檔案，不會連網。舊版留存資料會另列為歷史參考。快取存在不代表遠端現在正常，也不代表目前還能接受這個賠率。")
    st.table(local_source_evidence(root))
    st.caption("訓練資料表中的來源標籤來自本機紀錄，不能取代逐筆原始資料核驗。")
    st.write("在每張組合的「為什麼推薦」內，可以查看實際抓取時間、來源網址、專家原始推牌與模型資料日期。沒有資料時會顯示未知。")

    st.header("5. 看一張推薦單的順序")
    st.markdown("1. 先核對賽事、玩法、讓分線與資料時間。\n2. 分清楚哪些是來源紀錄，哪些是模型估計。\n3. 看估計命中率是否超過打平門檻，並用較低的勝率試算。\n4. 查看已結算樣本與歷史誤差，再判斷估計是否可信。")
    st.caption("模型估計尚未完成實證校準，因此不提供信賴區間或保守 EV。市場基準與模型估計分開呈現；正 EV 與 HIGH 情報都不能視為已證實的獲利能力。訓練資料中的來源標籤也不等於逐筆原始資料已核驗。")

    st.header("6. 國際權威盤口去水 (Sharp De-vig) 與真正的 +EV")
    st.markdown(
        """
        ### 為什麼瘋狗流串關必須依賴「去水」？
        台灣運彩的平均抽水（Vig / Margin）高達 **10%～15%**（俗稱水錢）。如果隨機下注 4 關串關，抽水效應會產生幾何級數複利侵蝕：
        $$\\text{Effective Margin} = 1 - (1 - 0.12)^4 \\approx 40\\%$$
        這意味著一般彩迷買 4 關，長期理論報酬率本質上是 **-40%**！

        ### 什麼是國際權威指標盤 (Sharp Benchmark)？
        國際頂尖博彩交易所（如 Pinnacle、Betfair）以極高流動性與極低抽水（1.5%～2.5%）聞名，其盤口被視為體育量化金融的「效率市場基準」。

        ### 去水公式 (Multiplicative De-vigging)
        設兩面盤賠率為 $O_1, O_2$，隱含總機率為：
        $$S = \\frac{1}{O_1} + \\frac{1}{O_2} > 1$$
        抽水比率為 $\\text{Vig} = S - 1$。
        去水後的真實無偏公允勝率（Fair Probability）為：
        $$P_1 = \\frac{1/O_1}{S}, \\quad P_2 = \\frac{1/O_2}{S}$$

        ### 判定正期望值 (+EV) 的唯一標準
        只有當 **台彩開出的賠率 $O_{\\text{taiwan}}$ 滿足以下條件時**，才算擁有實質統計優勢：
        $$\\text{EV} = P_{\\text{sharp\\_fair}} \\times O_{\\text{taiwan}} - 1 > 0$$
        本系統在串關篩選中，以綠色標籤 `🟢 正期望值 (+EV)` 標註此類珍貴組合，協助玩家擺脫負 EV 陷阱！
        """
    )

    st.header("7. 凱利準則 (Kelly Criterion) 與資金控管試算")
    st.markdown(
        """
        ### 為什麼玩運彩一定要資金控管？
        即使擁有正期望值 (+EV) 的策略，如果每次下注金額過大，在隨機波動（Variance / Drawdown）中依然有極高機率**破產（Gambler's Ruin）**。
        每週固定 **NT$ 200** 的風控鐵律，就是最堅固的防火牆。

        ### 凱利公式 (Kelly Formula)
        $$f^* = \\frac{b \\cdot p - q}{b} = \\frac{p \\cdot O - 1}{O - 1} = \\frac{\\text{EV}}{O - 1}$$
        - $f^*$：建議下注佔總資金的比例
        - $O$：賠率（小數制，含本金）
        - $b = O - 1$：淨賠率
        - $p$：真實現行勝率（去水後）
        - $q = 1 - p$：失敗機率

        ### 穩健銀行家 vs 瘋狗高倍率的資金分配策略
        - **穩健銀行家模式 (Banker 1.5x ~ 6x)**：勝率高（約 35% ~ 60%），建議採用 **1/4 Kelly (凱利分數的一刻)**，每單下注 NT$ 20 ~ NT$ 50，穩定滾大儲備池。
        - **瘋狗流高倍率 (Crazy Dog 10x ~ 100x+)**：勝率低（約 1% ~ 5%），即使理論 EV 為正，$f^*$ 建議比例也極低（< 1%），切忌重注！固定微額投注（每單 NT$ 10 ~ NT$ 20），以小博大，享受以小擊大的純粹娛樂。
        """
    )

    k_col1, k_col2, k_col3 = st.columns(3)
    with k_col1:
        kelly_bankroll = st.number_input("目前錢包資金 (NT$)", min_value=10.0, max_value=50000.0, value=200.0, step=50.0, key="kelly_bankroll")
    with k_col2:
        kelly_odds = st.number_input("目標串關賠率 (倍)", min_value=1.1, max_value=1000.0, value=3.0, step=0.5, key="kelly_odds")
    with k_col3:
        kelly_win_prob = st.slider("去水真實勝率估計 (%)", min_value=1, max_value=99, value=45, step=1, key="kelly_prob")

    p = kelly_win_prob / 100.0
    b = kelly_odds - 1.0
    q = 1.0 - p
    ev_k = (p * kelly_odds) - 1.0
    full_kelly_f = max(0.0, (b * p - q) / b) if b > 0 else 0.0
    quarter_kelly_f = full_kelly_f * 0.25

    full_stake = round(kelly_bankroll * full_kelly_f, 1)
    quarter_stake = round(kelly_bankroll * quarter_kelly_f, 1)

    km1, km2, km3 = st.columns(3)
    km1.metric("理論 EV", f"{ev_k * 100:+.1f}%")
    km2.metric("Full Kelly (全凱利注金)", f"NT$ {full_stake:.1f} ({full_kelly_f * 100:.1f}%)" if ev_k > 0 else "0 (負EV不宜投注)")
    km3.metric("1/4 Kelly (穩健建議注金)", f"NT$ {quarter_stake:.1f} ({quarter_kelly_f * 100:.1f}%)" if ev_k > 0 else "0 (負EV不宜投注)")


