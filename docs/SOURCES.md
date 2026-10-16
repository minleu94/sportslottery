# 系統數據來源與模型清單 (SOURCES.md)

本文件定義系統中所有外部數據來源、開源模型、API 以及它們在系統三層架構（Layer A / B / C）中的角色與權限。

---

## 數據來源清單矩陣

| Source ID | Source Name | Role | Sport | Live | GitHub Repo / Package | License | Used For | Can Generate Bet? |
| :--- | :--- | :--- | :--- | :---: | :--- | :---: | :--- | :---: |
| **`playsport_taiwan_odds`** | 玩運彩台彩盤口鏡像 | `BETTING_MARKET` | ALL (棒/足/籃/美足) | **LIVE** | `CharlieAlex/Sports-Betting-Freerider` (架構借鑑) | MIT | **產生唯一合法的台灣運彩投注選項與台彩實際賠率** | **YES** |
| **`playsport_taiwan_experts`**| 玩運彩大神主推排行榜 | `EXPERT` | ALL | **LIVE** | 自建 Vue JSON Parser | MIT | 取得經歷史驗證之真實榜首殺手推薦記錄 | **NO** (僅輔助評估) |
| **`playsport_crowd_consensus`**| 玩運彩社群大眾預測比例 | `CROWD` | ALL | **LIVE** | 玩運彩預測比例爬蟲 | Proprietary | 呈現一般彩迷大眾選票（嚴禁偽裝為大神） | **NO** (僅輔助評估) |
| **`penaltyblog_poisson`** | Penaltyblog Dixon-Coles / Poisson | `PREDICTION` | 足球 (SOCCER) | **LIVE** | `martineastwood/penaltyblog` (v1.12.2) | MIT | 依進球期望值計算足球勝平負與大小分開源模型評估 | **NO** (僅輔助評估) |
| **`pybaseball_mlb_model`** | Pybaseball Pythagorean Expectation | `PREDICTION` | 棒球 (MLB) | **LIVE** | `jldbc/pybaseball` (v2.2.7) | MIT | 計算 MLB 球隊攻守得分期望與畢氏勝率模型評估 | **NO** (僅輔助評估) |
| **`espn_public_scoreboard`** | ESPN 公開賽程 Scoreboard API | `SCHEDULE` | MLB / NFL / NBA / 足球 | **LIVE** | `sportsdataverse/sportsdataverse-py` | Open | 提供賽季雷達即時賽程與開賽時間日程認知 | **NO** (不得決定下注) |

---

## 嚴格原則宣告

1. **唯一投注核心**：只有標記 `BETTING_MARKET` 的來源（台灣運彩實際盤口）能產出 `TaiwanLeg` 進入串關候選池。
2. **賠率計算鐵律**：所有 10x ~ 500x 串關之總賠率乘積，**100% 必須使用台灣運彩實際賠率 (`taiwan_odds`)**，絕不允許使用國外賠率替代。
3. **大神與社群嚴格分離**：`EXPERT` 必須具備榜首/殺手歷史戰績證明；一般大眾投票比例嚴格標記為 `CROWD`。
4. **開源模型角色清晰**：`penaltyblog` 與 `pybaseball` 為真正的 GitHub/PyPI 開源套件，只負責輸出 `PredictionSignal` 供 Signal Hub 綜合研判，不可越權決定投注項目。
