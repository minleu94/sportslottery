# 跨運動開源預測模型深度調研報告 (GITHUB_MODEL_RESEARCH_V2.md)

**調研日期**：2026-09-18  
**調研目標**：深入調查全球開源社群（GitHub）中針對棒球（MLB/NPB/CPBL）、足球（英超/西甲/歐冠等）、籃球（NBA）、美式足球（NFL）等各項運動之開源預測引擎，嚴格評估其即時推論能力、維護狀態、授權協議、API 依賴與對齊台灣運彩盤口（不讓分、讓分、大小分）之可行性。

---

## 1. 跨運動開源預測引擎比較矩陣

| Repo | 運動 | 評估今日賽事 (Runs Today) | 維護狀態 (Maintained) | 授權 (License) | 需付費 API (Needs Paid API) | 輸出格式 (Output) | 台灣運彩對齊能力 (Taiwan Mapping) | 結論與判定 (Verdict) |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- | :--- |
| **[martineastwood/penaltyblog](https://github.com/martineastwood/penaltyblog)** | 足球 (Soccer) | **是** (內建 Dixon-Coles, Poisson 模型，可直接傳入歷史賽果 .fit() 後 .predict()) | 活躍 (v1.12.2, 2024) | MIT | **否** (純演算法庫，支援開放數據源) | 雙變量進球機率矩陣 (`FootballProbabilityGrid`: home_win, draw, away_win, total_goals) | **極高**：精確對齊台彩「不讓分（勝平負）」、「大小分（Over/Under 1.5/2.5/3.5）」與「讓分（Handicap）」 | **首選採用 (OPEN_SOURCE_ENGINE)**：足球頂級開源推論引擎，即時訓練與機率預測完全可用。 |
| **[fivethirtyeight/data](https://github.com/fivethirtyeight/data)** (MLB Elo) | 棒球 (MLB) | **是** (開放式公式與 Elo 基準，支援主客場優勢 +24 與先發投手調分) | 歷史典範 (公式開放，社群持續跟進) | CC-BY-4.0 / MIT | **否** (公開公開數據與歷史權重) | 主客隊勝率機率（Win Probability） | **高**：直接對齊台彩「不讓分（獨贏）」；經 Run Line 轉換對齊「讓分（-1.5/+1.5）」 | **採用 (OPEN_SOURCE_ENGINE / PUBLIC_MODEL)**：權威開源 Elo 算法，作為棒球獨立模型。 |
| **[jldbc/pybaseball](https://github.com/jldbc/pybaseball)** | 棒球 (MLB) | **否** (僅為數據爬取庫，無預先包裝之今日比賽預測器) | 活躍 (v2.2.7, 2024) | MIT | **否** (抓取 Baseball-Reference / Statcast / FanGraphs) | DataFrame (球員進階數據、打擊初速、投手自責) | **低**：無現成台彩賠率與盤口對齊介面，需二次開發複雜特徵工程 | **不作為模型引擎**：定位為底層數據庫，不得偽稱其為預測模型。本專案將基於其公式之腳本重命名為 `ESPNPythagoreanMLBModel` (LOCAL_FALLBACK_MODEL)。 |
| **[gmalbert/baseball-predictions](https://github.com/gmalbert/baseball-predictions)** | 棒球 (MLB) | **否** (歷史訓練腳本，相依已過期之 2018-2020 數據結構) | 停滯 (2021) | MIT | 否 | 二元分類勝率 (Logistic / LightGBM) | **中**：需手動抓取今日先發並重新映射特徵 | **不採用**：缺乏即時 pipeline，維護度不足。 |
| **[Torvaney/footy-predictor](https://github.com/Torvaney/footy-predictor)** | 足球 (Soccer) | **部分** (需外部注入歷史賽果) | 停滯 (2021) | MIT | 否 | 獨立 Poisson 比分期望值 | **中**：功能已被 `penaltyblog` 完全涵蓋且超前 | **不採用**：`penaltyblog` 為更成熟之超集。 |
| **[veekun/nba_predictions](https://github.com/veekun/nba_predictions)** | 籃球 (NBA) | **否** (模型腳本需本機歷史 SQLite DB，未維護即時更新) | 停滯 (2020) | GPL-3.0 | 否 | 主隊勝率與讓分覆蓋率 | **中**：可映射台彩讓分與獨贏 | **暫緩**：非球季期間，且無即時抓取今日先發陣容能力。 |
| **[cooperdff/nfl_predict](https://github.com/cooperdff/nfl_predict)** | 美式足球 (NFL) | **否** (賽季模型，依賴 nflfastR 數據管道) | 2023 | MIT | 否 | 點差 (Spread) 與總分 (Total) 迴歸值 | **中**：可對齊台彩 NFL 盤口 | **儲備中**：NFL 賽季期間可整合，目前優先打磨 MLB 與足球。 |
| **日本職棒 (NPB) 開源模型** | 棒球 (NPB) | **無** | - | - | - | - | - | **NO SUITABLE ENGINE FOUND**：GitHub 上無可直接運行的 NPB 預測引擎。必須依賴 Verified Taiwan Experts、大眾熱度與本機畢氏定理基礎。 |
| **中華職棒 (CPBL) 開源模型** | 棒球 (CPBL) | **無** | - | - | - | - | - | **NO SUITABLE ENGINE FOUND**：GitHub 上無維護成熟之 CPBL 機器學習推論引擎。以 Playsport 榜首大神為核心情報源。 |

---

## 2. 深度分析：足球頂級開源引擎 `penaltyblog`

### 2.1 為什麼 `penaltyblog` 是唯一的真正開源足球預測標準？
`penaltyblog`（作者 Martin Eastwood）是體育博弈分析界最受讚譽的 Python 工具庫之一：
1. **內建 Dixon & Coles (1997) 雙變量 Poisson 模型**：
   - 解決了傳統 Poisson 分布低比分（0-0, 1-0, 0-1, 1-1）相關性失真問題。
   - 導入球隊進攻強度（Attack Strength）與防守強度（Defence Strength）參數估計。
   - 透過歷史賽果數據（`home_team`, `away_team`, `home_goals`, `away_goals`）進行最大概似估計（MLE）擬合。
2. **輸出與台灣運彩 100% 精準對齊**：
   - 呼叫 `model.predict(home_team, away_team)` 會產出 `FootballProbabilityGrid`。
   - `grid.home_win` $\to$ 台彩不讓分主勝。
   - `grid.draw` $\to$ 台彩不讓分和局。
   - `grid.away_win` $\to$ 台彩不讓分客勝。
   - `grid.total_goals("over", line)` $\to$ 台彩大小分「大」。
   - `grid.total_goals("under", line)` $\to$ 台彩大小分「小」。
   - `grid.asian_handicap(line)` $\to$ 台彩讓分盤口。
3. **內建回測與評估指標**：
   - 支援 `penaltyblog.metrics.brier_score` 與 `rps` (Ranked Probability Score)，可即時監控預測準確度與機率校準。

---

## 3. 深度剖析：棒球 (MLB) 開源生態真相與架構重定

### 3.1 `pybaseball` 的真實本質
- `pybaseball` 是一個**數據抓取與封裝工具箱（Scraper & Statcast Interface）**，其主要功能是從 Baseball Reference、Fangraphs、Statcast 下載球員與球隊歷史數據。
- `pybaseball` **本身從未提供即時今日對戰勝率預測器（Game Outcome Predictor）**。
- **過去產品的命名虛假問題**：上一代架構中將本機使用 ESPN 官網得失分計算的畢氏定理腳本命名為 `PybaseballMLBAdapter` 並標記為外部開源模型，這是誤導性的包裝。
- **本次修正決定**：
  1. 正式更名為 `ESPNPythagoreanMLBModel`。
  2. 嚴格標記來源類型為 `LOCAL_FALLBACK_MODEL`。
  3. 宣告獨立來源群組為 `ESPN_SEASON_STATS`。
  4. 同步引進純粹基於公開 Elo 理論的 `FiveThirtyEightMLBEloAdapter` 作為 `OPEN_SOURCE_ENGINE`，宣告獨立來源群組 `FIVETHIRTYEIGHT_ELO`。

---

## 4. 亞洲職棒 (NPB / CPBL) 的誠實判定

在全面檢索 GitHub（搜尋關鍵字包括 `cpbl prediction`, `npb betting model`, `taiwan sports lottery python`）：
- **客觀事實**：目前 GitHub 上**完全沒有**具備即時推論管道、自動排程、能對應今日賽程之 NPB 或 CPBL 成熟開源預測模型。
- **產品策略**：
  - **絕不偽造**虛假模型，絕不自稱有「GitHub NPB Machine Learning Model」。
  - 判定為 **`NO SUITABLE ENGINE FOUND`**。
  - 對亞洲職棒賽事，情報來源嚴格由 **Layer A: 台灣玩運彩榜首大神 (Verified Taiwan Experts)** 與 **社群選票熱度 (Crowd Consensus)** 主導，輔以本機統計常數。若無驗證大神推牌，系統誠實標記為 `INSUFFICIENT_SIGNAL`，絕不勉強推薦。

---

## 5. 來源獨立性分組架構 (Independence Groups)

為防止多個模型使用同一份底層數據而產生「偽共識（Fake Consensus）」，系統建立嚴格的獨立性群組：

| 獨立性群組代碼 | 代表來源 | 數據基底 | 限制規則 |
| :--- | :--- | :--- | :--- |
| `TAIWAN_MARKET` | 台灣運彩官方盤口 | 威剛開盤賠率 | 僅作為市場基準（Baseline），**永遠不得計入支援票數** |
| `PLAYSPORT_EXPERT` | 玩運彩排行榜大神 | 專家個人預測頁面實體注單 | 單一獨立群組（權重最高） |
| `PLAYSPORT_CROWD` | 玩運彩投注比例 | 台灣廣大彩迷社群選票 | 單一獨立群組（大眾熱度參考） |
| `DIXON_COLES_MATCHES` | `penaltyblog` Dixon-Coles | 歷史單場對戰進球紀錄（Match-by-Match） | 獨立模型群組（開源推論引擎） |
| `ESPN_SEASON_STATS` | `ESPNPythagoreanMLBModel` / `ESPNPoissonSoccerFallback` | ESPN 賽季總得失分、場次、勝率 | 統計數據群組（若兩個同群組模型同時評估，**合計僅算 1 票**） |
| `FIVETHIRTYEIGHT_ELO` | `FiveThirtyEightMLBEloAdapter` | 歷史 Elo 積分矩陣與滾動累積 | 獨立推論群組 |

---
