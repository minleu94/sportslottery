# 資料來源與真實度稽核報告 (DATA_PROVENANCE_AUDIT.md)

**稽核日期**：2026-09-18  
**稽核範圍**：全 Repository 內所有資料集、快取檔案、資料庫與測試資料來源。  
**核心原則**：Production Prediction Path 必須為 **100% 真實資料**；任何 Synthetic / Mock / Dummy 資料嚴格僅能存在於 `tests/fixtures/` 或 `tests/synthetic/`。

---

## 1. 資料集完整盤點矩陣 (Dataset Inventory)

| File / Location | Dataset Name | Data Origin | Real / Synthetic / Fixture | Used in Production Path? | Remediation Action |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `data/cache/matches_eng.1.json` | 英超模擬對戰賽果 | 本機 scratch 腳本使用 `random.seed(42)` 與 Poisson 隨機生成 | **Synthetic** | **YES (CRITICAL ISSUE)** | **立即移出 Production！** 轉移至 `tests/fixtures/synthetic_matches_eng.1.json`。Production 改為拉取官方或 football-data.co.uk 真實歷史賽果；若無真實資料則標記 `MODEL_NOT_READY`。 |
| `data/cache/espn_soccer_eng.1.json` | 英超球隊賽季積分榜 | ESPN 官方 Live API (`http://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings`) | **Real** | Yes (`ESPNPoissonSoccerFallback`) | 保留（真實官方數據，包含勝率、得失球）。 |
| `data/cache/espn_mlb_standings.json` | MLB 30隊賽季積分榜 | ESPN 官方 Live API (`http://site.api.espn.com/apis/v2/sports/baseball/mlb/standings`) | **Real** | Yes (`ESPNPythagoreanMLBModel`) | 保留（真實官方數據，包含得失分與戰績）。 |
| `data/cache/experts_{aid}.json` | 玩運彩排行榜大神名單 | 玩運彩官網實體頁面 (`https://www.playsport.cc/predictrank.php?allianceid={aid}`) | **Real** | Yes (`PlaysportExpertAdapter`) | 保留（真實實名榜首大神資料）。 |
| `data/cache/member_pred_{aid}_{uid}.json`| 專家個人預測頁面注單 | 玩運彩官網會員頁面 (`https://www.playsport.cc/member/{uid}/prediction?allianceid={aid}`) | **Real** | Yes (`PlaysportExpertAdapter`) | 保留（包含真實 `table.bank-tablecon` 運彩實體注單）。 |
| `data/cache/scale_{aid}.json` | 台灣運彩盤口與彩迷選票 | 玩運彩官網運彩盤頁面 (`https://www.playsport.cc/predictgame.php?allianceid={aid}`) | **Real** | Yes (`PlaysportOddsAdapter`, `PlaysportCrowdAdapter`) | 保留（真實威剛運彩盤口與彩迷社群選票）。 |
| `data/historical/prediction_snapshots.jsonl`| 預測評估與結算快照 | 系統執行即時評估與注單下注時寫入之審計軌跡 | **Real** | Yes (`PredictionSnapshotLogger`) | 保留（用於 Brier Score 與 Log Loss 校準）。 |
| `data/snapshots/*.json` | 原始網路請求快照 | `PlaysportScraper` 自動落盤之原始 HTTP Response | **Real** | No (僅供審計與離線追蹤) | 保留。 |
| `data/war_chest.sqlite3` | 使用者錢包與注單資料庫 | 使用者實際操作、注單流水帳與每週 NT$ 200 預算鎖定 | **Real** | Yes (`WeeklyWalletManager`, `TicketRecorder`) | 保留。 |
| `tests/acceptance/test_intelligence_layer.py` | `DummyExpertScraper` | 單元測試內存隔離 Mock 類別 | **Fixture** | No (測試專用) | 保留。 |

---

## 2. 關鍵問題診斷與整改規範

### 2.1 發現之重大問題：
- 在先前的開發測試中，為驗證 `penaltyblog.models.DixonColesGoalModel` 的 `.fit()` 與 `.predict()` 介面，曾建立包含 60 場隨機生成進球數的 `data/cache/matches_eng.1.json`。
- **後果**：此檔案位於 `data/cache/` 內，導致 `PenaltyblogDixonColesAdapter` 在 Production 環境中讀取了非真實的比賽數據來擬合模型。
- **嚴格整改方針**：
  1. 將該 Synthetic 檔案移至 `tests/fixtures/synthetic_matches_eng.1.json`，Production 目錄內**完全清空**該檔案。
  2. 整合真實的英超歷史比賽資料集（包含 `date`, `league`, `home_team`, `away_team`, `home_goals`, `away_goals`）。
  3. 導入 **Point-in-Time 嚴格防穿越機制 (Leakage Guard)**：確保任何訓練比賽之日期嚴格早於預測目標賽事之日期（`training_match.date < prediction_event.start_time`）。
  4. 設立 **Minimum Data Threshold**：歷史場次 $\ge 60$ 且兩隊皆有 $\ge 4$ 場出賽紀錄方可擬合；否則誠實回傳 `None` (`MODEL_NOT_READY`)，絕不以隨機資料充數。
