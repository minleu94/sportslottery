# 台灣運彩瘋狗流決策系統 - 程式碼真實性審計報告 (AUDIT_REPORT.md)

**審計日期**：2026-09-18  
**審計目標**：全面排查 `C:\Projects\PythonProjects\sportslottery` 現有程式碼真實度、資料來源、模型真偽與資料血統（Data Lineage），杜絕任何未經說明的 Mock 與自造 Heuristic。

---

## 總體評級摘要

| 模組名稱 | 檔案路徑 | 真實度狀態評級 | 核心問題摘要 |
| :--- | :--- | :--- | :--- |
| **Season Radar** | `core/season_radar.py` | **PARTIAL / HARDCODED FALLBACK** | 未實際呼叫 ESPN API；僅依賴已爬取的 playsport 盤口數，無盤口時完全回退至硬編碼月份 (`default_season`)。 |
| **Odds / Lottery Scraper** | `core/scraper.py` | **LIVE (Playsport.cc Scraper)** | 真實對 Playsport 發出 HTTP 請求，取得台灣運彩盤口與賠率；但在連線失敗時含有靜態 Mock 回退 (`_fallback_matches`)。非台彩官方 API。 |
| **Expert Recommendations** | `core/signal_hub.py` | **MOCK / SYNTHETIC** | **嚴重問題**：抓取了排行榜，但在評估選項時，`expert_ratio = min(0.95, consensus_ratio * 1.15)`，**將大眾投票比例乘以 1.15 偽裝成大神看好度**！ |
| **Open-source Model** | `core/signal_hub.py` | **NOT IMPLEMENTED** | **嚴重問題**：`_open_model_estimate` 僅為自寫 Heuristic 公式 `0.65 * (1/odds) + 0.35 * consensus`，**無任何真實 GitHub 專案或開源套件**！ |
| **Signal Hub** | `core/signal_hub.py` | **CIRCULAR / FAKE INDEPENDENCE** | 4 個訊號中有 3 個由 `odds` 與 `consensus_ratio` 衍生，訊號間高度循環依賴，`HIGH` 一致度實為假象。 |
| **Parlay Engine** | `core/parlay_engine.py` | **LIVE (Rule-based Search)** | 具備真實台彩同場互斥過濾與組合搜尋，但分類依賴虛假的 Signal 一致度。 |
| **Weekly Wallet** | `core/wallet.py` | **LIVE (SQLite State)** | SQLite 狀態管理正常，落實 NT$ 200 限額與 Prize Pool，需強化新週邊界與防追單鎖定。 |
| **Ticket Recorder** | `core/ticket_recorder.py` | **LIVE (SQLite Persistence)** | 真實持久化下注單與結算流水。 |

---

## 細項審計

### A. Season Radar 審計
- **資料來源**：
  - 程式碼內定義了 `espn_slug`（例如 `baseball/mlb`），但**從未在任何執行路徑中向 ESPN API 發出請求**。
  - 目前邏輯為：若傳入的 `live_matches` 中包含該聯盟代碼，且比賽數 > 0，則標記為 🟢；若無比賽，則檢查當前月份是否落在 `default_season: (start_m, end_m)` 區間，若在區間內標 🟡，否則標 🔴。
- **真實狀態**：`PARTIAL / HARDCODED`
- **改善方案**：整合真實的公開賽程 API（ESPN 公開 Scoreboard API：`http://site.api.espn.com/apis/site/v2/sports/...`）取得當日實際賽程，並以「台灣運彩是否有開盤」作為 🟢/🟡 之嚴格分界。

---

### B. Odds / Taiwan Sports Lottery Data 審計
- **資料來源**：`https://www.playsport.cc/predict/scale?allianceid={aid}`
- **更新頻率**：設有 15 分鐘本地 Cache，支援強制重新整理。
- **支援聯盟**：Alliance 1 (MLB), 4 (足球), 93 (NFL), 2 (NPB), 6 (CPBL), 7 (WNBA/NBA), 87 (NHL)。
- **支援玩法**：讓分、不讓分、大小、和局。
- **實測 Live Request 證據**（2026-09-18 測試）：
  - `GET https://www.playsport.cc/predict/scale?allianceid=1` $\to$ **HTTP 200 OK** (回傳 203,916 bytes)
  - 成功解析 9 場 MLB 賽事，第一場：釀酒人 (116) vs 海盜。
  - 賠率屬於「台灣運彩威剛盤口」在玩運彩網站上的鏡像，非台灣運彩官網直接提供之 API（官方無 API）。
- **真實狀態**：`LIVE (第三方爬蟲)`。若斷網或解析失敗，內含 fallback mock (`FB_101`)。

---

### C.「大神推薦」審計
- **來源探索**：
  - `core/scraper.py` 中確實實作了 `fetch_expert_leaderboard(alliance_id)`，自 `https://www.playsport.cc/billboard/mainPrediction?allianceid=1` 抓取真實榜首（例如「社會我瓜哥」勝率 94%）。
  - **實測證據**：`GET https://www.playsport.cc/billboard/mainPrediction?allianceid=1` $\to$ **HTTP 200 OK** (回傳 70,793 bytes)。
- **致命缺失**：
  - 在 `core/signal_hub.py` 的 `evaluate_option()` 中，**完全沒有把爬下來的大神主推比賽與當前選項做比對**！
  - 而是寫了這行假代碼：
    ```python
    expert_ratio = min(0.95, consensus_ratio * 1.15) if consensus_ratio > 0.60 else consensus_ratio * 0.90
    expert_count_approx = max(1, min(10, int(expert_ratio * 10)))
    ```
  - **這是把「大眾投票比例」包裝成「8/10 位高手看好」！**
- **真實狀態**：**MOCK / 偽造資料血統**。必須立即廢除此假公式，改為真正比對專家推薦資料，若無資料則誠實顯示 `INSUFFICIENT SIGNAL`。

---

### D. Open-source Model 審計
- **模組宣稱**：`core/signal_hub.py` 中的 `_open_model_estimate`。
- **程式碼實際內容**：
  ```python
  def _open_model_estimate(self, odds: float, consensus: float, market_type: str) -> float:
      base_p = 1.0 / odds if odds > 1.0 else 0.5
      adj = 0.65 * base_p + 0.35 * consensus
      return round(max(0.05, min(0.92, adj)), 3)
  ```
- **審計結論**：
  - **GitHub URL**: 無
  - **Repo / Author / License**: 無
  - **實際為自寫之線性混合 Heuristic**。
- **真實狀態**：**NOT IMPLEMENTED**。
  不能將自己寫的 `0.65 * base + 0.35 * crowd` 偽稱為開源統計模型。必須在 Phase 1~3 真正引入成熟開源庫（如 `penaltyblog` 的 Dixon-Coles/Poisson 模型、FiveThirtyEight Elo / Pythagorean 模型）。

---

### E. Signal Hub Data Lineage 審計
以某場比賽的 `HIGH` 評級為例，其目前的資料血統追蹤如下：
```text
[輸入資料]
1. 賠率 odds = 1.45
2. 大眾投票 consensus_ratio = 0.78
        │
        ├──> Market Signal: 1 / 1.45 = 69% (支持)
        ├──> Crowd Signal: 0.78 >= 0.58 (支持)
        ├──> Expert Signal: 0.78 * 1.15 = 90% -> 9/10 高手 (支持) [偽造]
        └──> Model Signal: 0.65*(0.69) + 0.35*(0.78) = 72% (支持) [偽造]
                │
                ▼
        [4 個訊號中有 4 個支持] -> 標記 🟢 HIGH
```
- **結論**：所謂的 4 個獨立訊號，本質上只有 **2 個原始輸入**（賠率與大眾票數），其餘 2 個皆為其數學變形，造成嚴重的虛假共識。

---

## 改善實施方向

1. **Season Radar**：接入 ESPN Public Scoreboard API，精準取得今日真實賽程；無盤口時標記 🟡，休賽季標記 🔴。
2. **Models & Signals**：
   - 接入真正成熟的開源模型（例如：足球採用 `penaltyblog` Poisson/Dixon-Coles 期望進球模型；棒球採用真實 MLB Pythagorean/Elo 期望模型）。
   - 專家訊號若無對應真實預測記錄，直接回傳 `None`，不可合成偽造。
3. **Signal Hub**：
   - 必須具備至少 2 個以上真正獨立的資料來源，才允許評為 `HIGH`。
   - 移除 `MOONSHOT` 作為信心等級，改為純賠率區間標籤。
4. **Source Registry & Adapters**：
   - 建立 `config/source_registry.yaml` 與 `integrations/` 轉接層，統一以 `PredictionSignal` 輸出，資料血統百分之百透明。
