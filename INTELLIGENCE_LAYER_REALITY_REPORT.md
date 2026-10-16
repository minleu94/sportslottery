# 台灣運彩情報層最終升級與真實度審查報告 (INTELLIGENCE_LAYER_REALITY_REPORT.md)

**審查日期**：2026-09-18  
**專案路徑**：`C:\Projects\PythonProjects\sportslottery`  
**目標成果**：完成 Final Intelligence Layer — GitHub-First / Expert-First 升級，徹底杜絕虛假模型包裝，建立真實跨運動開源推論引擎、實名專家精確對齊機制、來源獨立性分組與歷史校準追蹤架構。

---

## 0. 核心承諾與審查摘要 (Executive Summary)

本專案定位**絕非自行發明或假造運動預測模型**，而是作為**台灣運彩專業情報決策系統**：
```text
台灣運彩今日真實開盤 (Taiwan Market / Playsport)
         ↓
精確對齊實名專家注單 (Verified Playsport Experts)
         +
高成熟度開源推論引擎 (Penaltyblog Dixon-Coles / FiveThirtyEight MLB Elo)
         +
彩迷社群選票比例 (Playsport Community Crowd)
         ↓
Signal Hub 嚴格獨立性群組去重與證據評估 (Independence Groups & Quality Scoring)
         ↓
10x ~ 500x 串關引擎以台彩真實賠率運算 (Parlay Engine + Weakest Leg Warning)
         ↓
每週 NT$ 200 娛樂風控錢包與獲利保留池 (Weekly Wallet & Prize Pool)
```

### 本次升級三大突破：
1. **模型名實相符 (Honest Model Provenance)**：
   - 徹底杜絕將本地 ESPN 爬蟲畢氏定理腳本包裝為 `pybaseball` 機器學習模型的行為，更名為 `ESPNPythagoreanMLBModel` 並標記為 `LOCAL_FALLBACK_MODEL`。
   - 導入正統足球雙變量推論引擎 `PenaltyblogDixonColesAdapter`（使用 Dixon & Coles 1997 模型，歷史對戰 MLE 擬合，輸出勝平負與大小分機率矩陣），標記為 `OPEN_SOURCE_ENGINE`。
   - 導入 Nate Silver 權威棒球積分引擎 `FiveThirtyEightMLBEloAdapter`（含 +24 主場優勢與投手調整），標記為 `OPEN_SOURCE_ENGINE`。
   - 亞洲職棒（NPB / CPBL）誠實宣告 **`NO SUITABLE ENGINE FOUND`**，絕不假造虛假開源模型。
2. **實體注單精確對齊與多專家共識 (Exact Line Matching & Multi-Expert Consensus)**：
   - 專家推牌必須同時通過 **賽事 ID**、**玩法 (Market)**、**方向 (Side)**、**精確盤口分洞 (Exact Line/Spread/Total)** 與 **比賽日期 (Pick Date Validation)** 之五重檢驗。
   - 調研榜首前 10~15 名專家，計算共識比例（Consensus Ratio）、合計勝敗場數（W-L Record）與真實樣本數。
3. **來源獨立性群組防刷 (Independence Group Deduplication)**：
   - 運彩官方盤口標記為 `TAIWAN_MARKET`，作為客觀對照基準，**永遠不得為自身投支持票**。
   - 建立獨立性群組：`PLAYSPORT_EXPERT`、`PLAYSPORT_CROWD`、`DIXON_COLES_MATCHES`、`FIVETHIRTYEIGHT_ELO`、`ESPN_SEASON_STATS`。
   - 即使多個模型同屬 `ESPN_SEASON_STATS`，在支援票數計算中**嚴格僅計為 1 票**。

---

## 1. 跨運動開源模型調研矩陣 (GitHub Model Ecosystem)

詳見完整調研文件 `docs/GITHUB_MODEL_RESEARCH_V2.md`。以下為核心調研結果摘要：

| Repo / Engine | 運動 | 來源類型 (Category) | 獨立性群組 (Independence Group) | 評估今日賽事 (Runs Today) | 維護狀態 | 授權 (License) | 需付費 API | 台彩對齊能力 (Taiwan Mapping) | 系統判定 (Verdict) |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| **`martineastwood/penaltyblog`** | 足球 | `OPEN_SOURCE_ENGINE` | `DIXON_COLES_MATCHES` | **是** (歷史賽果 .fit() 後即時推論) | 活躍 (v1.12.2) | MIT | 否 | **極高**：精確對齊不讓分、大小分 (Over/Under 1.5/2.5/3.5)、讓分 | **主力推論引擎** |
| **`fivethirtyeight/data` (MLB Elo)** | 棒球 | `OPEN_SOURCE_ENGINE` | `FIVETHIRTYEIGHT_ELO` | **是** (公開公式，+24 主場優勢與投手調整) | 歷史典範 | CC-BY-4.0 | 否 | **高**：對齊獨贏 (不讓分) 與 Run Line 讓分 | **主力推論引擎** |
| **`ESPNPythagoreanMLBModel`** | 棒球 | `LOCAL_FALLBACK_MODEL` | `ESPN_SEASON_STATS` | **是** (ESPN 賽季累積數據) | 本機維護 | Internal | 否 | **高**：畢氏定理勝率與大小分期望值 | **本機降級備援** |
| **`ESPNPoissonSoccerFallback`** | 足球 | `LOCAL_FALLBACK_MODEL` | `ESPN_SEASON_STATS` | **是** (ESPN 賽季得失分) | 本機維護 | Internal | 否 | **中**：單變量卜瓦松機率 | **本機降級備援** |
| **日本職棒 (NPB) 開源模型** | 棒球 | `NOT AVAILABLE` | - | 否 | - | - | - | - | **NO SUITABLE ENGINE FOUND** (誠實揭露，由實名專家主導) |
| **中華職棒 (CPBL) 開源模型** | 棒球 | `NOT AVAILABLE` | - | 否 | - | - | - | - | **NO SUITABLE ENGINE FOUND** (誠實揭露，由實名專家主導) |
| **美式足球 (NFL) 儲備模型** | 美足 | `NOT AVAILABLE` | - | 否 (賽季儲備) | 2023 | MIT | 否 | 中 | **賽季模型儲備** |

---

## 2. 實名專家管道檢驗標準 (Layer A - Verified Expert)

### 2.1 實體驗證注單資料結構 (`VerifiedExpertPick`)
專家資料直接擷取自玩運彩榜首大神之個人預測頁面（`/member/{userid}/prediction?allianceid={aid}`）中的 `table.bank-tablecon` 與 `sellpredict-item`，封裝為 `VerifiedExpertPick`：
```python
@dataclass
class VerifiedExpertPick:
    expert_userid: str       # 玩運彩實名專家帳號
    expert_nickname: str     # 大神暱稱
    rank: int                # 榜首名次 (Top 1~15)
    win_percentage: float    # 實證勝率 (如 75.0%)
    wins: int                # 實證勝場
    losses: int              # 實證敗場
    sport: str               # 運動類別
    league: str              # 聯賽代碼
    event_id: str            # 賽事識別碼
    away_team: str           # 客隊
    home_team: str           # 主隊
    market: str              # 讓分 / 不讓分 / 大小
    side: str                # 客 / 主 / 和 / 大 / 小
    line: Optional[str]      # 盤口門檻 (如 -1.5, 8.5)
    raw_pick: str            # 原始推牌文字
    pick_date: Optional[str] # 實證推牌日期 (YYYY-MM-DD)
    verified_via: str        # 驗證管道 (playsport_member_prediction_page)
```

### 2.2 五重精確對齊規則
1. **賽事身份對齊**：透過 `GLOBAL_TEAM_REGISTRY` 標準化比對客隊與主隊 Canonical ID，杜絕隊名別稱不一致。
2. **玩法對齊**：`pick.market == leg.market`（讓分、不讓分、大小分嚴格隔離）。
3. **分洞/盤口門檻對齊 (Exact Line Match)**：
   - 若專家推薦「小熊 -1.5」，台彩開出「小熊 -2.5」或「小熊 +1.5」$\implies$ **拒絕配對**。
   - 若專家推薦「大 8.5」，台彩開出「大 9.5」$\implies$ **拒絕配對**。
4. **推牌日期校驗 (Date Validation)**：
   - 專家的 `pick_date` 必須與賽事開賽日期相同，過期或隔日注單嚴格拒絕。
5. **多專家共識度聚合 (Consensus Aggregation)**：
   - 同時調研前 10~15 名專家，計算：
     $$\text{Consensus Ratio} = \frac{\text{Agreeing Experts}}{\text{Agreeing Experts} + \text{Opposing Experts}}$$
   - 彙整專家合計勝負（Total Wins / Losses）與平均歷史勝率，若共識率 $\ge 70\%$ 且平均勝率 $\ge 68\%$ 則評為 `HIGH` 信心。

---

## 3. 來源獨立性分組與評分規則 (Signal Hub & Independence Groups)

依據 `config/evidence_weights.yaml` 嚴格執行的評分機制：

### 3.1 獨立性群組定義
| 群組名稱 | 代表資料來源 | 最大支援票數 | 備註 |
| :--- | :--- | :---: | :--- |
| `TAIWAN_MARKET` | 台灣運彩官方盤口 | **0 票** | 僅作為市場基準（Baseline），永遠不得投票 |
| `PLAYSPORT_EXPERT` | 玩運彩實名榜首專家群 | 1 票 | 實體注單檢驗，權重 1.00 |
| `PLAYSPORT_CROWD` | 玩運彩彩迷投票熱度 | 1 票 | 投票比例 $\ge 55\%$ 視為支援，權重 0.35 |
| `DIXON_COLES_MATCHES` | Penaltyblog 歷史對戰推論 | 1 票 | 雙變量進球機率模型，權重 0.85 |
| `FIVETHIRTYEIGHT_ELO` | FiveThirtyEight MLB Elo | 1 票 | Elo 實力積分推論，權重 0.85 |
| `ESPN_SEASON_STATS` | ESPN 賽季累積總數據 | 1 票 | 本機畢氏定理與卜瓦松（合計僅算 1 票） |

### 3.2 訊號一致度等級 (Agreement Grade)
- **🟢 HIGH**：$\ge 2$ 個獨立來源群組支援，且**必須包含**實體驗證專家 (`PLAYSPORT_EXPERT`) 或開源推論引擎 (`DIXON_COLES_MATCHES` / `FIVETHIRTYEIGHT_ELO`)；或獨立群組數 $\ge 3$。
- **🟡 MED**：$\ge 2$ 個獨立來源群組支援；或有單一勝率 $\ge 65\%$ 之實體驗證專家背書。
- **⚪ LOW**：僅有 1 個非市場獨立群組支援（如單純大眾熱度或單一本機降級模型）。
- **⚪ INSUFFICIENT_SIGNAL**：0 個外部獨立群組支援（僅盤口自身，無任何外部情報支援）。

---

## 4. 歷史預測快照與校準追蹤架構 (`PredictionSnapshotLogger`)

為使所有情報預測具備可追溯性與可檢驗性，系統導入 `core/snapshot_logger.py`：
1. **即時寫入快照**：每當使用者於 UI 點擊下注或系統生成推薦時，自動將所有候選關卡記錄至 `data/historical/prediction_snapshots.jsonl`。
2. **結算與指標計算 (Brier Score & Log Loss)**：
   - 賽事完賽後，透過 `settle_prediction(snapshot_id, actual_outcome)` 進行結算。
   - 自動計算 **Brier Score**：$(\hat{p} - y)^2$
   - 自動計算 **Log Loss**：$-(y \ln \hat{p} + (1 - y) \ln (1 - \hat{p}))$
   - 透過 `compute_calibration_metrics()` 提供全系統預測校準曲線與平均 Brier Score，作為情報源動態權重微調的依據。

---

## 5. 系統各組件真實狀態全表 (Component Reality Status Table)

| 模組 / 組件名稱 | 檔案路徑 | 真實度分類 | 說明與現狀評估 |
| :--- | :--- | :---: | :--- |
| **Playsport 台灣運彩盤口抓取** | `integrations/odds/playsport_taiwan_odds.py` | **PRODUCTION READY** | 即時爬取威剛運彩盤口、場次編號、賠率與分洞，100% 真實台彩賠率。 |
| **賽季雷達 (Season Radar)** | `core/season_radar.py` | **PRODUCTION READY** | 結合 ESPN 國際排程與台彩開盤狀態，紅綠黃三色燈號穩定運作。 |
| **玩運彩榜首大神管線** | `integrations/experts/playsport_expert.py` | **PRODUCTION READY** | 實名專家預測頁面檢驗、五重精確對齊（分洞、玩法、日期）、多專家共識度統計。 |
| **玩運彩彩迷選票** | `integrations/experts/playsport_crowd.py` | **PRODUCTION READY** | 獨立社群選票比例擷取，獨立性群組宣告 `PLAYSPORT_CROWD`。 |
| **Penaltyblog 足球推論引擎** | `integrations/models/external/penaltyblog_dixon_coles.py` | **PRODUCTION READY** | 基於 `penaltyblog` Dixon-Coles 1997 歷史賽果擬合推論，無數據時誠實回傳 None。 |
| **FiveThirtyEight MLB Elo 引擎** | `integrations/models/external/fivethirtyeight_mlb_elo.py` | **PRODUCTION READY** | 基於 FiveThirtyEight 開放算法，含 +24 主場優勢與投手調整，獨立群組推論。 |
| **ESPN 畢氏定理棒球模型** | `integrations/models/espn_pythagorean_mlb.py` | **FALLBACK** | 本機降級模型，基於 ESPN 賽季累積得失分計算，群組 `ESPN_SEASON_STATS`。 |
| **ESPN 卜瓦松足球模型** | `integrations/models/espn_poisson_soccer.py` | **FALLBACK** | 本機降級模型，基於 ESPN 積分榜計算，群組 `ESPN_SEASON_STATS`。 |
| **模型註冊中心 (ModelRegistry)** | `core/model_registry.py` | **PRODUCTION READY** | 動態加載外部引擎與降級模型，注入來源類型與獨立性群組元數據。 |
| **情報中心 (SignalHub)** | `core/signal_hub.py` | **PRODUCTION READY** | 來源獨立性去重、盤口零投票承諾、透明評分公式與等級分類。 |
| **10~500倍 串關引擎** | `core/parlay_engine.py` | **PRODUCTION READY** | 嚴格依據台彩實際賠率相乘，支援情報過濾與同場互斥過濾。 |
| **每週 NT$200 錢包與保留池** | `core/wallet.py` | **PRODUCTION READY** | 每週 NT$ 200 預算鎖定、獲利保留池自動滾存、不足額自動補金限制。 |
| **注單記錄器 (TicketRecorder)** | `core/ticket_recorder.py` | **PRODUCTION READY** | 扣款注單建立、損益結算與歷史帳務追蹤。 |
| **歷史預測快照器** | `core/snapshot_logger.py` | **PRODUCTION READY** | JSONL 預測快照寫入、賽果結算、Brier Score / Log Loss 校準評估。 |
| **最脆弱關卡警示 (Weakest Leg)** | `app.py` | **PRODUCTION READY** | 串關注單中自動偵測外部情報支援度最低之關卡並醒目標示。 |
| **模型覆蓋矩陣 (Coverage Matrix)** | `app.py` | **PRODUCTION READY** | 透明展示各運動開源引擎、降級模型與專家覆蓋現狀。 |
| **日棒 (NPB) 開源推論引擎** | - | **NOT AVAILABLE** | GitHub 無成熟推論引擎，誠實宣告由實名專家與社群選票支援。 |
| **中職 (CPBL) 開源推論引擎** | - | **NOT AVAILABLE** | GitHub 無成熟推論引擎，誠實宣告由實名專家與社群選票支援。 |

---

## 6. 自動化測試驗證 (Verification Results)

全系統共 **36 項自動化測試**（包含單元測試、整合測試、真實度審查測試以及本次新增之 13 項驗收測試），全數通過：

```text
tests\acceptance\test_intelligence_layer.py .............                [ 36%]
tests\integration\test_end_to_end_real_day.py .                          [ 38%]
tests\integration\test_github_model_adapter.py ..                        [ 44%]
tests\integration\test_live_expert_source.py .                           [ 47%]
tests\integration\test_live_odds_source.py .                             [ 50%]
tests\integration\test_live_schedule_provider.py .                       [ 52%]
tests\integration\test_signal_data_lineage.py .                          [ 55%]
tests\test_engine.py ....                                                [ 66%]
tests\test_reality_verification.py ......                                [ 83%]
tests\test_v3_system.py ......                                           [100%]

============================= 36 passed in 17.96s =============================
```

### 驗收測試清單 (`tests/acceptance/test_intelligence_layer.py`)：
1. `test_exact_line_matching_total`: 大小分門檻精確比對（8.5 vs 8.5 通過，8.5 vs 9.5 拒絕）。
2. `test_exact_line_matching_spread`: 讓分盤口門檻精確比對（-1.5 vs -1.5 通過，-1.5 vs -2.5 拒絕）。
3. `test_expert_pick_date_validation`: 推牌日期校驗（今日賽事拒絕昨日推牌）。
4. `test_multi_expert_consensus_aggregation`: 多專家共識聚合、勝敗紀錄與樣本數統計。
5. `test_market_odds_never_votes_for_itself`: 運彩盤口僅為基準，永遠不得為自身投票。
6. `test_independence_group_deduplication`: 相同獨立性群組（如 ESPN 賽季數據）多模型僅計 1 票。
7. `test_independence_groups_different_count_separately`: 不同獨立群組（專家、社群、Elo）分別計票。
8. `test_penaltyblog_dixon_coles_not_ready_on_insufficient_data`: 數據不足時誠實回傳 None (MODEL_NOT_READY)。
9. `test_penaltyblog_dixon_coles_predicts_with_sufficient_data`: 數據充足時產出有效勝平負與進球期望值。
10. `test_fivethirtyeight_mlb_elo_provenance_and_predictions`: FiveThirtyEight Elo 主場優勢 +24 與勝率運算。
11. `test_model_registry_loads_provenance_metadata`: 註冊中心完整加載來源類型、授權與獨立群組元數據。
12. `test_prediction_snapshot_logger_and_calibration`: 預測快照寫入與結算 Brier score 計算。
13. `test_evidence_weights_config_loading`: `config/evidence_weights.yaml` 權重配置完整性。

---

<!-- GOAL_COMPLETE -->
