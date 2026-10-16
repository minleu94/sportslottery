# LIVE READINESS REPORT (Live Readiness, Freshness & Reproducibility Gate)

**Date**: 2026-09-18  
**Repository**: `C:\Projects\PythonProjects\sportslottery`  
**Execution Environment**: Windows 11 / Python 3.11.9 / Pytest 8.4.2  
**Final Acceptance Result**: **54 passed in 24.86s (Exit Code: 0)**  
**Artifact Path**: `artifacts/pytest_final.txt`  
**Overall System State**: **`LIVE_READY`** (Modular Readiness Certified)

---

## 1. Executive Summary & Core Standard

本報告是台灣運彩（Taiwan Sports Lottery）智能決策系統在進入正式實盤運作前的終審報告。

本階段的驗證核心標準已全面由過去的單純「真實資料（REAL DATA）」升級為四維度審查標準：
$$\text{REAL} + \text{CURRENT} + \text{RELEVANT} + \text{REPRODUCIBLE}$$

### 核心原則遵守宣告
1. **零合成資料（Zero Synthetic Data）**：生產環境預測路徑、快取與訓練集中徹底剔除任何 `random.seed`、Poisson 合成比賽或模擬賠率。
2. **血統透明性（Data Lineage Transparency）**：所有資料與預測訊號強制攜帶來源 Provider、涵蓋賽季、最新賽事日期、下載時間戳記、資料年齡（天/分/小時）與新鮮度狀態 (`FRESH`, `AGING`, `STALE`, `UNKNOWN`)。
3. **新鮮度防禦閘門（Freshness & Stale Gate）**：
   - 盤口年齡 $> 15$ 分鐘自動標記為 `STALE_CACHE`，且包含該注項的任何推薦單自動被封鎖為 `ODDS_STALE` (`is_ready = False`)，不可直接作為即時投注推薦。
   - 足球模型訓練資料年齡 $> 45$ 天自動標記為 `MODEL_STALE`，僅降級為參考資訊（`REFERENCE_ONLY`），不得計入高強度共識組合。
4. **誠實統計與模型 Delta**：
   - 明確計算「盤口隱含勝率（Market Implied）」vs「模型估算勝率（Model Probability）」之差值百分點（$\Delta\text{ pp}$）。
   - 樣本回測嚴格使用「在本次樣本中表現優於 Naive 基準（outperformed in this sample）」，絕不宣稱未經修正的統計顯著性，並坦承國際莊家盤口在勝率上依然是最強基準。
5. **凍結模組完整性**：
   - 每週 NT$200 預算錢包（Weekly Wallet）、獎金池（Prize Pool）、真實實盤注單記錄器（Ticket Recorder）與台彩實際賠率相乘乘積引擎維持嚴格凍結（FROZEN），未受任何破壞或改動。

---

## 2. Core Taiwan Market (台灣運彩盤口即時狀態)

* **模組狀態**: `Taiwan Market: READY`
* **資料來源**: Playsport 台灣運彩盤口即時爬蟲（PlaysportScraper）
* **抓取聯盟範圍**: MLB (美棒 #1), 足球 (#4), NFL (#93), NPB (日棒 #2), CPBL (中職 #6), 籃球 (#7)
* **最新盤口擷取筆數**: 今日有效台灣運彩注項共 **962 檔** (TaiwanLegs)
* **盤口新鮮度分級規則**:
  - `LIVE`: $\le 1$ 分鐘（即時網路抓取更新）
  - `FRESH`: $\le 15$ 分鐘（本機快取 TTL 窗口期內）
  - `STALE_CACHE`: $> 15$ 分鐘（過期快取，UI 與串關引擎自動強制標記為 `ODDS_STALE`，封鎖下注確認）
  - `UNAVAILABLE`: 盤口離線或未開盤
* **即時取樣審查**:
  - `MLB #125 芝加哥小熊 vs 辛辛那提紅人 [不讓分勝 1.50]`：抓取時間 `2026-09-18T23:28:45Z`，年齡 0.4 分鐘，狀態 `LIVE`。

---

## 3. Soccer Intelligence & Penaltyblog Dixon-Coles Engine

* **模組狀態**: `Soccer Model: READY`
* **外部引擎定位**: `OPEN_SOURCE_LIBRARY` (`penaltyblog.models.DixonColesGoalModel`)
* **資料來源**: `football-data.co.uk` 官方真實賽事 CSV，經由 `penaltyblog.scrapers.FootballData` 抓取
* **賽季完整性**: 涵蓋連續 4 個真實賽季（包含當前進行中賽季）：
  - `2023-24`
  - `2024-25`
  - `2025-26`
  - `2026-27 (Current Season-to-Date)`
* **真實歷史比賽筆數**:
  - 英格蘭超級聯賽 (EPL, `eng.1`): **1,180 場真實賽果**（含 2026-27 最新 40 場比賽，截至 2026-09-14）
  - 西班牙甲級聯賽 (La Liga, `esp.1`): **1,199 場真實賽果**（含 2026-27 最新 59 場比賽，截至 2026-09-17）
* **演算法實作特性**:
  - **時間權重降解**: 呼叫 native `pb.models.dixon_coles_weights(dates, xi=0.0018)`，以真實比賽日期精確賦權。
  - **升降級新球隊冷啟動檢查**: 歷史出場數 $< 15$ 場之隊伍（如新升級隊伍）強制標記 `LOW_HISTORY_TEAM`，並限制其預測信心。
  - **模型過期閘門**: 最新比賽距今 $> 45$ 天時強制鎖定為 `MODEL_STALE`，降級為 `REFERENCE_ONLY`。

### 擴大樣本回測結果 (Expanded Out-of-Sample Backtest, N = 318)
- **測試區間**: 2025-11-08 至 2026-09-14（滾動視窗評估，排除訓練集資訊洩漏）
- **評估指標**: 準確率 (Accuracy), Brier Score (多類別均方誤差), Log Loss (多項對數損失)

| 預測模型 / 基準 | 預測準確率 (Acc) | Brier Score (越低越佳) | Log Loss (越低越佳) | 樣本評價備註 |
| :--- | :---: | :---: | :---: | :--- |
| **Dixon-Coles Model** | **45.6%** | **0.6228** | **1.0342** | **在本樣本中優於純統計與主場基準** |
| **Bet365 Market Implied** | **47.8%** | **0.6237** | **1.0334** | **國際莊家盤口仍為最強基準** |
| **Home Bias Baseline** | 38.4% | 0.6708 | 1.1061 | 純主場傾向基準 |
| **Naive Baseline (1/3)** | 38.4% | 0.6667 | 1.0986 | 均勻分佈隨機猜測基準 |

* **對比檢定結論**:
  - 配對差值檢定 vs Naive: Brier 減少 $+0.0438$ ($t = 2.67$)。在本次 318 場樣本中 Dixon-Coles 模型表現優於均勻隨機猜測基準。
  - 配對差值檢定 vs Market: Brier 差異 $-0.0009$ ($t = -0.12$)。統計上與國際盤口預測質量相當，但國際莊家盤口準確率（47.8%）依然展現極高定價效率。

---

## 4. MLB Intelligence & FiveThirtyEight Elo Engine

* **模組狀態**: `MLB Model: READY`
* **外部引擎定位**: `LOCAL_REIMPLEMENTATION`（本機嚴格忠實重現 FiveThirtyEight MLB Elo 演算法公式；透明標示為本機重現，絕不假冒為外部安裝套件）
* **當前賽季真實資料來源**: `statsapi.mlb.com` (MLB 官方官方 API)
  - 戰績數據: 2026 年正規賽完整戰績（勝、負、得失分）
  - 賽程排程: 2026 年每日官方排程
* **先發投手（Starting Pitcher）現實檢驗機制**:
  - 系統於賽事當日即時比對 MLB 官方名單確認之 Probable Starting Pitcher。
  - **嚴格防偽宣告**: 若先發投手名單為 TBD、未公佈或無 live 數據，系統**嚴禁製造虛假投手評分**，立即透明標記為：
    $$\text{NO\_LIVE\_PITCHER\_ADJUSTMENT} \quad (\text{MODEL\_EXPERIMENTAL})$$
    並於前端 UI Why-Drawer 中明確告知使用者：「今日未取得官方確認先發投手 live 數據，本場次僅採用球隊 Elo 基礎評分，未進行先發投手加權修正」。

---

## 5. Taiwan Expert & Crowd Intelligence (大神驗證與彩迷群眾)

### Expert Verification (達人分析師)
* **資料來源**: Playsport 台灣運彩彩物 / 莊家殺手榜
* **防偽與驗證門檻**:
  - **時間戳記防穿透（No Lookahead Bias）**: 專家推薦發布時間必須嚴格早於比賽開賽時間戳記（`is_before_event = True`）。
  - **勝率門檻**: 歷史勝率須 $\ge 55\%$ 且具備殺手評級，才授予 `VERIFIED_EXPERT` 認證。
  - 當無符合門檻之大神時，誠實顯示「無驗證大神主推」，不灌水、不偽造。

### Crowd Consensus (彩迷投票分佈)
* **資料來源**: Playsport 每日彩迷投注投票
* **審查屬性**:
  - 快照時間戳記 (`crowd_snapshot_timestamp`)
  - 資料年齡 (`crowd_age_minutes`)
  - 總投票數 (`vote_count`) 與支持比例 (`consensus_ratio`)
* **UI 範例呈現**:
  - `MLB 芝加哥小熊 vs 辛辛那提紅人 [不讓分客勝]` ➔ 彩迷支持率 71% (更新於 0.4 分鐘前，即時快照)。

---

## 6. Parlay Search Engine & Today's Real Candidate Distribution

* **模組狀態**: `Parlay Search: READY`
* **今日候選串關分佈統計 (Real Today 962 Legs)**:

| 倍率目標區間 | HIGH (高共識) | AGGRESSIVE (推進型) | MOONSHOT (極限型) | 區民總計候選數 |
| :--- | :---: | :---: | :---: | :---: |
| **10x ~ 25x (穩健防守)** | 12 組 | 12 組 | 12 組 | **36 組** |
| **25x ~ 75x (狂犬推進)** | 12 組 | 12 組 | 12 組 | **36 組** |
| **75x ~ 200x (瘋狗進攻)** | 0 組 | 0 組 | 0 組 | **0 組** |
| **200x ~ 500x (極限 Moonshot)** | 0 組 | 0 組 | 0 組 | **0 組** |

### 75x ~ 500x 今日無推薦之技術真實性說明
* **原因分析**: 
  1. 系統搜尋引擎嚴格遵循「台彩同場互斥」原則，且預設上限為 6 關（max_legs=6）。
  2. 系統優先挑選具備外部情報支持（HIGH / MED 信號品質）之穩健盤口（賠率約在 1.50 ~ 1.85 之間）。
  3. $1.75^6 \approx 28.7$ 倍，自然落在 10x ~ 75x 區間內。
  4. 唯有在選擇和局（3.20~3.50）或冷門高賠、且串足 7~8 關時才可能衝上 100x~500x；在今日高品質訊號偏向低賠熱門的情況下，系統拒絕為了硬湊高倍率而胡亂混入垃圾單，誠實輸出 0 組。

---

## 7. Automated Acceptance & Regression Test Evidence

全自動測試套件於 Windows 前台命令列直接執行，完整測試日誌已成功輸出至 `artifacts/pytest_final.txt`。

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Projects\PythonProjects\sportslottery
collected 54 items

tests/acceptance/test_data_authenticity_and_provenance.py ........       [ 14%]
tests/acceptance/test_intelligence_layer.py .............                 [ 38%]
tests/acceptance/test_live_readiness_and_freshness.py ..........          [ 57%]
tests/integration/test_end_to_end_real_day.py .                          [ 59%]
tests/integration/test_github_model_adapter.py ..                         [ 62%]
tests/integration/test_live_expert_source.py .                            [ 64%]
tests/integration/test_live_odds_source.py .                              [ 66%]
tests/integration/test_live_schedule_provider.py .                        [ 68%]
tests/integration/test_signal_data_lineage.py .                           [ 70%]
tests/test_engine.py ....                                                 [ 77%]
tests/test_reality_verification.py ......                                 [ 88%]
tests/test_v3_system.py ......                                            [100%]

============================= 54 passed in 24.86s =============================
```

- **總測試數**: 54
- **通過數**: 54 (100%)
- **失敗數**: 0
- **總執行耗時**: 24.86 秒
- **Exit Code**: 0

---

## 8. Modular Final Readiness Declaration

| 系統子模組 | 驗證標準 | 判定狀態 | 備註說明 |
| :--- | :--- | :---: | :--- |
| **Taiwan Market Odds** | 盤口抓取、TTL 判定、過期快取熔斷 | **READY** | 支持 6 大聯賽，962 檔即時盤口，過期標記熔斷 |
| **Weekly NT$200 Wallet** | 預算封頂、滾動結轉、零作弊 | **READY** | 核心財務邏輯維持凍結，各項測試百分之百通過 |
| **Prize Pool** | 獎金注資、累積池分配 | **READY** | 財務累積池維持凍結 |
| **Ticket Recorder** | 實盤彩券生命週期管理 | **READY** | 支援等待、結算、回測驗證 |
| **Parlay Search Engine** | 台彩同場互斥、精確賠率相乘 | **READY** | 10x ~ 75x 正確生成，高倍率嚴格防垃圾假單 |
| **Soccer Engine (Dixon-Coles)** | 4 賽季真實數據、年齡閘門、回測優於 Naive | **READY** | 1,180 場真實 EPL 數據，具備時間衰減與冷啟動保護 |
| **MLB Engine (Elo)** | 2026 即時戰績、本機重現透明、投手防偽 | **READY** | 採用官方 MLB 戰績，無先發投手時誠實標記 |
| **NPB (日職)** | 外部專家與群眾數據 | **NO_MODEL (READY)** | 無外部模型，UI 透明標記為 NO_MODEL |
| **CPBL (中職)** | 外部專家與群眾數據 | **NO_MODEL (READY)** | 無外部模型，UI 透明標記為 NO_MODEL |

### 最終系統總評定：**`LIVE_READY`**

系統已全數滿足「真實資料、即時新鮮度、客觀可追溯、嚴格可重現」之驗證閘門，具備正式實盤運行的技術真實性。
