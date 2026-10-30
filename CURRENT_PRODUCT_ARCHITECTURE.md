# 台灣運彩「瘋狗流」10~500倍 高倍串關決策系統
# 目前產品真實架構、資料流與完成度審查報告 (CURRENT_PRODUCT_ARCHITECTURE.md)

**文件版本**：v1.0 (Codebase Reality Audit) -> v2.3.0 Modern Architecture Note  
**審查日期**：2026-09-18 (歷史基準) | 2026-10-30 (v2.3.0 升級補充)  
**基準專案路徑**：`C:\Projects\PythonProjects\sportslottery`  
**審查原則**：Technical Reality Only（依實際程式碼執行路徑為唯一依據，不美化、不猜測、不掩飾任何 Heuristic 與 Facade）。

> [!NOTE]
> **版本演進說明（2026-10-30，v2.3.0 Modern Edition）**：  
> 本文件第 1~4 節紀錄了 2026-09-18 初始版本（Streamlit 單機架構）之原始審查歷史；系統現已正式升級為 **v2.3.0 現代化單端口架構**：
> 1. **前端技術棧**：全量遷移為 React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui + Lucide Icons + Framer Motion，支援程式碼分割與 iPhone Safari PWA。
> 2. **後端服務架構**：以 FastAPI（Port 8000）統一承載前端靜態檔案、REST API 與 `/callback` LINE Webhook，不再依賴多端口轉發。
> 3. **公網與行動端連線**：由系統匣管理器統一掛載 ngrok 永久固定專屬網域 `https://fifty-saddlebag-immortal.ngrok-free.dev`（或 Cloudflare 隧道備援），支援 0.0.0.0 區域網路 Wi-Fi 手機連線。
> 4. **資安防護**：PIN 碼全面升級為 PBKDF2-HMAC-SHA256 16 位元組 Salt 雜湊儲存，所有玩家資產操作全面要求 32 位元組加密 Session Token 驗證。
> 最新維運與指令細節，請參閱 [docs/AGENT_HANDOFF_AND_LINE_BOT_MANUAL.md](docs/AGENT_HANDOFF_AND_LINE_BOT_MANUAL.md)。

---

# 1. 一句話說明目前產品到底是什麼

### 技術現實本質（Technical Reality）
本產品目前是一個**「以玩運彩（Playsport）網頁爬蟲鏡像為盤口基礎、本機 SQLite 為每週 NT$200 風控帳本、搭配啟發式計票規則與 itertools 組合搜尋的單機 Streamlit 運彩決策輔助看板」**。

具體說明如下：
1. **真正解決的問題**：提供台灣運彩彩迷在「每週最高 NT$ 200 外部損失上限」與「贏錢全數鎖入獲利保留池」的嚴格資金風控下，自動在當日台彩開盤賽事中，篩選出符合 10x ~ 500x 目標賠率、且符合單場互斥過關規則的串關組合，防止非理性無上限賭博。
2. **使用者打開後可以做什麼**：
   - 在「今日可玩 (賽季雷達)」查看今日台灣運彩實際開盤聯賽與場次。
   - 在「瘋狗看盤」拉動 10~500 倍滑桿並挑選運動種類，產生跨賽事 2~6 串 1 組合，展開 Why 證據抽屜檢視盤口與情報，點擊「確認下注」扣除每週錢包額度。
   - 在「資金紀錄」進行本週外部補金、提領獲利池、手動點擊「恭喜中獎」或「標記未過關」完成注單結算。
3. **哪些功能是真正 LIVE 的**：
   - 玩運彩台灣運彩盤口爬蟲（即時爬取讓分、不讓分、大小分、和局與實際賠率）。
   - 玩運彩彩迷社群投票比例與票數（真實提取 `consensus_ratio` 與 `vote_count`）。
   - 玩運彩殺手/大神排行榜榜首名單擷取（即時擷取 billboard 頁面內嵌 Vue JSON）。
   - ESPN 公開 Scoreboard REST API 賽程抓取。
   - 本地 SQLite 每週 NT$200 錢包、獲利保留池滾存狀態機與注單流水帳。
   - 串關搜尋引擎（嚴格以台彩真實賠率連乘，嚴格過濾同場賽事衝突）。
4. **哪些功能目前只是 PROTOTYPE / HEURISTIC / FACADE / FALLBACK**：
   - **國外開源模型（`pybaseball`, `penaltyblog`）**：**名義整合，實質 Facade**。套件雖已安裝，但 adapter 內完全未傳入真實歷史數據、比賽陣容或進階統計；而是用寫死數值（足球寫死 xG=1.55/1.15；MLB 依台彩賠率 1.50/1.80 寫死投射得分）套公式計算。
   - **大神主推（`PlaysportExpertAdapter`）**：**名義大神，實質 Heuristic 合成**。爬到了排行榜榜首（如「社會我瓜哥」94%勝率），但**完全沒有爬取該大神到底買了哪一場**；程式碼用「若賠率 <= 2.20 且大眾選票 >= 60%」就自動貼上該榜首名稱與勝率。
   - **隊名解析與事件對齊**：**Prototype 字符串切割**。直接以空白截斷文字取前 10 字元，遇到先發投手文字會誤把投手名字當隊名（例如把 Cincinnati Reds 解析為 "Clay"）；無跨來源 Canonical ID 對齊。
   - **官方自動下注與自動結算**：**未實作（Not Implemented）**。下注與開獎結算全依賴人工在 UI 上點擊。
   - **離線降級（Fallback）**：若 Playsport 網路中斷且無快取，退回硬編碼之「道奇 vs 巨人」假資料。

---

# 2. Current Product Flow

以下為系統目前**真實執行的代碼路徑**（非理想設計）：

```text
[使用者啟動應用]
      ↓
main.py (子進程啟動 streamlit run app.py)
      ↓
app.py: get_system_components()
      ↓
┌────────────────────────────────────────────────────────────────────────┐
│ TAB 1: 賽季雷達 (Season Radar)                                          │
│ 1. PlaysportOddsAdapter.get_taiwan_legs(["1","4","93","6","2","7"])    │
│    → HTTP GET playsport.cc/predict/scale?allianceid=X (快取15分)       │
│    → 解析 HTML 表格 → 產出今日真實 TaiwanLeg 清單                      │
│ 2. SeasonRadar.get_radar_summary(taiwan_legs, check_live_espn=True)    │
│    → HTTP GET site.api.espn.com/apis/site/v2/sports/.../scoreboard    │
│    → 比對：若該聯盟在台彩盤口數 > 0 ➔ 🟢 GREEN                         │
│           若台彩無盤但 ESPN 有賽程/處賽季月 ➔ 🟡 YELLOW                  │
│           若休賽季 ➔ 🔴 RED                                            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────┐
│ TAB 2: 瘋狗看盤 (10~500倍 串關 & Signal Hub)                            │
│ 1. 使用者於 UI 選擇目標倍率 (如 25x~75x) 與混串運動 (MLB/足球/NFL等)    │
│ 2. PlaysportOddsAdapter 取得候選賽事 TaiwanLeg 清單                     │
│ 3. SignalHub.evaluate_taiwan_leg(leg) 進行逐注情報評估：                 │
│    ├─ [BETTING_MARKET] 台彩盤口隱含勝率 (1/odds)                       │
│    ├─ [CROWD] 玩運彩大眾投票比例 (consensus_ratio)                      │
│    ├─ [EXPERT] 榜首大神啟發式合成 (若賠率<=2.2且投票>=60% ➔ 掛上榜首)    │
│    └─ [MODEL] 開源模型 Facade 推論:                                     │
│         ├─ MLB: 依賠率區間硬編碼投射得分 ➔ Bill James 畢氏勝率公式       │
│         └─ 足球: 硬編碼 xG (1.55, 1.15) ➔ Scipy 泊松分佈機率            │
│ 4. SignalHub 計算支援數 (external_supports) ➔ 🟢 HIGH / 🟡 MED / ⚪     │
│ 5. ParlayEngine.search_parlays():                                      │
│    ├─ 每場比賽剪枝保留前 2 個選項，候選池取前 16 場賽事                 │
│    ├─ itertools.combinations(event_ids, num_legs) 確保【同場互斥】     │
│    ├─ itertools.product(*options) 計算組合總賠率 (100% 台彩賠率連乘)    │
│    └─ 分流為 3 個桶: 🟢 共識較高 / 🟡 比較瘋 / 🔴 極限 Moonshot         │
│ 6. 使用者展開 Why 抽屜檢視各關卡依據，確認注金 (預設 NT$20)             │
│ 7. 使用者點擊「📝 確認下注」                                            │
│    → TicketRecorder.place_ticket()                                     │
│    → WeeklyWalletManager.stake_bet() 扣除本週可玩餘額 (驗證 <= 餘額)    │
│    → SQLite tickets 表新增狀態 'OPEN' 注單                             │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────┐
│ TAB 3: 資金紀錄 (Weekly Wallet & Tickets)                              │
│ 1. 每週狀態檢驗 (WeeklyWalletManager._ensure_week_initialized):        │
│    → 檢測 ISO 週別。若跨週：優先自 Prize Pool 提撥最多 NT$200至錢包     │
│ 2. 外部補金: deposit_external() 嚴格檢查 (餘額+已注+補金 <= NT$ 200)   │
│ 3. 獲利提領: withdraw_from_prize_pool() 自 Prize Pool 領出至真實銀行   │
│ 4. 人工開獎結算:                                                       │
│    ├─ 使用者點擊「🎉 恭喜中獎」➔ 派彩金 100% 寫入 Prize Pool           │
│    └─ 使用者點擊「❌ 標記未過關」➔ 注單標記 LOST，錢包餘額不變          │
└────────────────────────────────────────────────────────────────────────┘
```

---

# 3. Current System Architecture

以下為目前 repository 內所有模組、檔案與資料夾的真實狀態盤點：

| Module/File | Responsibility | Inputs | Outputs | Live Dependency | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `app.py` | Streamlit 互動主介面（三頁籤、頂部資金條、Why 抽屜、下注控制） | Web Browser 請求、使用者輸入 | Streamlit DOM、呼叫各 core 模組 | 依賴所有底層模組 | **LIVE** |
| `main.py` | 系統入口啟動腳本，呼叫 Subprocess 啟動 Streamlit | CLI 命令 | 本機服務進程 (Port 8501) | Python 3.11 環境 | **LIVE** |
| `core/season_radar.py` | 賽季與開盤雷達判定（🟢/🟡/🔴 三色燈判定） | TaiwanLeg 清單、ESPN 事件 | 各聯賽雷達摘要字典清單 | `ESPNScheduleAdapter` | **LIVE** |
| `core/scraper.py` | Playsport 網頁爬蟲、快取存取、快照備份、降級資料 | HTTP 請求、聯盟編號 | 賽事清單、盤口選項、排行榜專家 | `requests`, `BeautifulSoup` | **LIVE** |
| `core/signal_hub.py` | 聚合盤口、大神、大眾、模型四路情報，計算一致性等級 | `TaiwanLeg` 物件 | 附加 `signal_evidence` 與 `signals` 之 Leg | Expert/Crowd/Model 適配器 | **LIVE** |
| `core/parlay_engine.py` | 10x~500x 串關搜尋引擎，嚴格同場互斥與台彩倍率連乘 | `TaiwanLeg` 清單、目標倍率 | 3 分類桶組合字典 (`high_consensus`, etc.) | 無 (純演算法運算) | **LIVE** |
| `core/wallet.py` | 每週 NT$200 資金風控、獲利保留池 (Prize Pool)、跨週結轉 | SQLite 連線、金額、週別 | 錢包狀態字典、帳本紀錄 | SQLite (`war_chest.sqlite3`) | **LIVE** |
| `core/ticket_recorder.py`| 注單生命週期記錄、下注扣款、人工開獎派彩入獲利池 | 關卡組合、注金、開獎狀態 | 注單物件、更新 SQLite | `WeeklyWalletManager` | **LIVE** |
| `core/model_registry.py` | 動態載入 `config/models.yaml` 註冊之預測模型 | `TaiwanLeg` | `PredictionSignal` 清單 | `importlib`, PyPI 套件 | **LIVE** |
| `core/optimizer.py` | 舊版基於 EV / fair_prob 排序之串關引擎 | 賽事字典清單 | 候選串關清單 | 無 | **UNUSED** (僅舊測試引用) |
| `core/war_chest.py` | 舊版單一資金池管理器（未嚴格區分錢包與獲利保留池） | SQLite 連線 | 現金流紀錄 | SQLite | **UNUSED** (僅舊測試引用) |
| `core/ticket_manager.py`| 舊版注單管理器（綁定舊版 WarChestManager） | 注單關卡、注金 | 注單紀錄 | 舊版 WarChest | **UNUSED** (僅舊測試引用) |
| `integrations/common/models.py` | 跨模組標準資料模型 (`TaiwanLeg`, `PredictionSignal`) | 資料欄位 | 結構化 Dataclass 物件 | 無 | **LIVE** |
| `integrations/odds/playsport_taiwan_odds.py` | Layer A 台灣運彩盤口適配器，轉化為標準 `TaiwanLeg` | 聯盟代碼清單 | `List[TaiwanLeg]` | `PlaysportScraper` | **LIVE** |
| `integrations/experts/playsport_expert.py` | Layer A 玩運彩殺手/大神榜適配器（啟發式貼標） | `TaiwanLeg` | `PredictionSignal` (EXPERT) | `PlaysportScraper` | **PARTIAL** (邏輯為 Heuristic) |
| `integrations/experts/playsport_crowd.py` | Layer A 彩迷社群投票比例適配器 | `TaiwanLeg` | `PredictionSignal` (CROWD) | Leg 內部 evidence | **LIVE** |
| `integrations/models/pybaseball_mlb_model.py` | Layer B MLB 畢氏勝率模型適配器 | `TaiwanLeg` | `PredictionSignal` (MODEL) | `pybaseball` (僅讀版本號) | **HARDCODED** (得分寫死) |
| `integrations/models/penaltyblog_soccer_model.py`| Layer B 足球 Poisson 進球期望模型適配器 | `TaiwanLeg` | `PredictionSignal` (MODEL) | `scipy`, `penaltyblog` (僅讀版本號) | **HARDCODED** (xG 寫死) |
| `integrations/schedules/espn_schedule.py` | Layer C ESPN 公開 Scoreboard 賽程適配器 | 運動代碼 (MLB/NFL等) | ESPN 事件清單 | ESPN REST API | **LIVE** |
| `config/models.yaml` | 模型註冊設定檔（定義套件、適配器路徑、權重） | YAML 文本 | 字典配置 | 無 | **LIVE** |
| `config/source_registry.yaml` | 資料來源總表（定義來源 ID、角色、權限、快取模式） | YAML 文本 | 字典配置 | 無 | **LIVE** |
| `probability/calibration.py` | 機率校準、Logit 收縮與保守信賴下限公式 | 機率、大眾份額 | 校準後機率 | 無 | **UNUSED** (未被任何模組呼叫) |
| `probability/devig.py` | 去水 (De-vig) 演算法（乘法去水、2-way/3-way 去水） | 賠率清單 | 公平機率、抽水率 | 無 | **UNUSED** (未被任何模組呼叫) |
| `collectors/__init__.py` | 資料採集套件佔位目錄 | 無 | 無 | 無 | **UNUSED** (空目錄) |
| `risk/__init__.py` | 風控套件佔位目錄 | 無 | 無 | 無 | **UNUSED** (空目錄) |
| `tickets/__init__.py` | 注單套件佔位目錄 | 無 | 無 | 無 | **UNUSED** (空目錄) |
| `optimizer/__init__.py` | 最佳化套件佔位目錄 | 無 | 無 | 無 | **UNUSED** (空目錄) |
| `data/cache/` | 磁碟快取目錄（存放 15 分鐘內的 JSON） | Scraper 資料 | JSON 檔案 | 本機檔案系統 | **LIVE** |
| `data/snapshots/` | 不可變歷程快照目錄（時間戳檔名） | Scraper 資料 | JSON 檔案 | 本機檔案系統 | **LIVE** |
| `data/war_chest.sqlite3` | SQLite 帳本資料庫（錢包狀態、流水帳、注單紀錄） | SQL 語句 | 資料表 Row | SQLite 引擎 | **LIVE** |
| `docs/SOURCES.md` | 資料來源清單文件 | Markdown | 文件 | 無 | **LIVE** |
| `docs/TAIWAN_GITHUB_RESEARCH.md` | 台灣開源專案調研報告 | Markdown | 文件 | 無 | **LIVE** |
| `tests/` (10 個測試腳本) | 單元測試與真實連線整合測試 | 測試案例 | Pytest 報告 | Pytest 引擎 | **LIVE** (17/17 通過) |

---

# 4. Taiwan Sports Lottery Layer

## 4.1 今天台灣運彩「可以買什麼」是怎麼取得的？
- **Source**：玩運彩網站（`playsport.cc`）之即時運彩盤鏡像。
- **URL/API**：`https://www.playsport.cc/predict/scale?allianceid={alliance_id}`
  - 聯盟代碼：`1` (MLB), `4` (足球), `93` (NFL), `6` (CPBL), `2` (NPB), `7` (NBA/WNBA)。
- **Parser**：`PlaysportScraper._parse_predict_table`
  - 使用 `BeautifulSoup` 抓取 `table.predictgame-table`。
  - 採單次遍歷逐行掃描 `tr`，抓取含有時間標記（AM/PM/:）的 Header 作為賽事起點。
  - 正規化提取官方賽事編號（如 `116` 或 `125`）、隊名、盤口格子內的選項與賠率。
- **Refresh mechanism**：
  - 前端 UI 提供「🔄 刷新即時盤口」按鈕，觸發 `st.cache_data.clear()` 與 `st.rerun()`。
  - 後端可傳入 `force_refresh=True` 繞過快取重抓。
- **Cache**：
  - 本地快取：`data/cache/scale_{alliance_id}.json`，TTL 為 900 秒（15 分鐘）。
  - 快照備份：每次爬取成功額外寫入 `data/snapshots/{YYYYMMDD_HHMMSS}_scale_{aid}.json`。
- **Failure behavior**：
  - 若 HTTP 非 200 或網路逾時（timeout=10s），優先讀取 `data/cache/` 內的過期快取（Stale Cache）。
  - 若本機完全無快取檔案，自動降級調用 `_fallback_matches()`，注入寫死之「道奇 vs 巨人」（`FB_1_101`）假資料，避免前端 Crash。

## 4.2 台灣運彩賠率從哪裡來？
```text
Taiwan odds:
Source: playsport.cc 運彩盤欄位 (台灣運彩威剛實體盤口鏡像)
Adapter: integrations.odds.playsport_taiwan_odds.PlaysportOddsAdapter
Example: 2026-09-18 MLB 賽事 #125 【小熊 vs Cincinnati】，小熊不讓分客勝賠率 1.52，大 8.5分 1.75
Freshness: 15 分鐘本機磁碟快取，支援手動即時強制刷新
Fallback: 過期快取 JSON -> 若無則使用 _fallback_matches 寫死賠率 (1.45, 1.75)
```

## 4.3 台灣運彩玩法如何 normalize？
在 `PlaysportScraper._classify_market` 中進行字串特徵正規化：

| Taiwan source market | 判斷條件 | internal market type | 範例正規化輸出 |
| :--- | :--- | :--- | :--- |
| **大小** | cell 字串開頭為 `大` 或 `小` | `大小` | `大 8.5分 (1.75)` |
| **讓分** | cell 含盤口數值（`line is not None`）且為客/主 | `讓分` | `小熊 -1.5 (1.92)` |
| **和局** | cell 字串為 `和` | `和局` | `和局 (3.20)` |
| **不讓分** | cell 無盤分門檻，純勝負（獨贏/Moneyline） | `不讓分` | `小熊 不讓分勝 (1.52)` |

**目前不支援**：勝分差、單雙、單節/半場盤、正確比數（波膽）。

## 4.4 台彩 event identity 怎麼跟外部模型對接？
### 明確事實：目前「完全沒有對接機制」。
1. **Canonical Event ID**：**無**。台彩使用 Playsport 賽事編號（如 `125`），ESPN 使用其內部全域 ID（如 `401695...`），兩者完全獨立，沒有跨來源 ID 對齊表。
2. **Team Alias Mapping**：**無**。目前程式碼直接以空白將網頁文字分割並取前 10 字元（`tokens[0][:10]`）。這導致若 Playsport 網頁文字包含先發投手（如「小熊 101 今永昇太 V.S. 紅人 102 Greene」），會將隊名與投手誤切（實測中曾將 Cincinnati Reds 誤切為客隊 "Clay"）。
3. **League Mapping**：**僅靠硬編碼**。以 Playsport 的 `alliance_id` 映射到固定字串（`"1"` ➔ MLB, `"4"` ➔ 足球）。
4. **Timezone Normalization**：**無**。直接保留原始爬蟲文字（如 `"AM 06:40"` 或 `"PM 10:00"`），無轉換為標準 ISO 8601 UTC 時間戳。
5. **外部模型如何對接？**：因為外部模型（`PybaseballMLBAdapter`, `PenaltyblogSoccerAdapter`）根本**沒有去查詢真實球隊資料庫**，而是直接接收 `TaiwanLeg` 裡面的 `taiwan_odds` 跑數學公式，因此在目前的程式碼中，「不需要對接隊名也能跑出數字」。

---

# 5. Season Radar 真正是怎麼工作的？

### 各聯盟雷達判定矩陣：

| League | Season source (月份) | Today game source | Taiwan market check | Current logic |
| :--- | :---: | :---: | :---: | :--- |
| **MLB** | 3 ~ 11 月 | Playsport `scale_1` + ESPN `MLB` | 檢查 `taiwan_legs` 內 MLB 場次 | 台彩有開盤 ➔ 🟢；台彩無開盤但 ESPN 有賽事 ➔ 🟡；非賽季 ➔ 🔴 |
| **NFL** | 9 ~ 2 月 | Playsport `scale_93` + ESPN `NFL` | 檢查 `taiwan_legs` 內 NFL 場次 | 同上 |
| **英超 (PREMIER)** | 8 ~ 5 月 | Playsport `scale_4` + ESPN `PREMIER` | 檢查 `taiwan_legs` 內足球場次 | 同上 |
| **歐冠 (CHAMPIONS)**| 9 ~ 6 月 | Playsport `scale_4` + ESPN `CHAMPIONS` | 檢查 `taiwan_legs` 內足球場次 | 同上 |
| **中華職棒 (CPBL)** | 3 ~ 10 月 | Playsport `scale_6` (無 ESPN) | 檢查 `taiwan_legs` 內 CPBL 場次 | 台彩有開盤 ➔ 🟢；無開盤但屬 3~10 月 ➔ 🟡；其餘 ➔ 🔴 |
| **日本職棒 (NPB)** | 3 ~ 11 月 | Playsport `scale_2` (無 ESPN) | 檢查 `taiwan_legs` 內 NPB 場次 | 同上 |
| **NBA** | 10 ~ 6 月 | Playsport `scale_7` + ESPN `NBA` | 檢查 `taiwan_legs` 內 NBA 場次 | 台彩有開盤 ➔ 🟢；無開盤但屬 10~6 月 ➔ 🟡；其餘 ➔ 🔴 |
| **NHL** | 10 ~ 6 月 | Playsport `scale_87` + ESPN `NHL` | 檢查 `taiwan_legs` 內 NHL 場次 | 同上（9月非賽季 ➔ 🔴） |
| **TPBL (台灣職籃)** | 10 ~ 5 月 | 無爬蟲 (無 aid, 無 ESPN) | 無開盤數據 | 依月份判斷：10~5月 ➔ 🟡，其餘 ➔ 🔴 |

### 關鍵審查問題回答：
### 🟢 Green 是否真的代表「今天台灣運彩有盤」？
**是的，100% 嚴格如此。**  
在 `core/season_radar.py` 第 162~174 行：
```python
if taiwan_market_count > 0:
    status = "GREEN"
    status_text = f"進行中 · 台彩今日開盤 ({taiwan_market_count}場)"
    light_emoji = "🟢"
elif in_season_calendar or espn_event_count > 0:
    status = "YELLOW"
    status_text = "賽季中 · 今日台彩無開盤"
    light_emoji = "🟡"
else:
    status = "RED"
    status_text = "休賽季"
    light_emoji = "🔴"
```
只要台灣運彩今天沒有開出該聯盟盤口（`taiwan_market_count == 0`），就算國外 ESPN 打得如火如荼，燈號也**絕對只能亮 🟡 黃燈**，絕不亮綠燈。

---

# 6. Current External Sources Registry Summary

| Source | Role | Sport | URL/Repo | Live? | Used in Prod? | What does it provide? |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| **Playsport 運彩盤** | `TAIWAN_BETTING_MARKET` | 全部 | `https://www.playsport.cc/predict/scale` | **LIVE** | **YES** | 台灣運彩官方賽事編號、對戰隊伍、開賽時間、讓分/不讓分/大小/和局實際賠率（全系統唯一能產生注單選項之來源）。 |
| **Playsport 大神榜** | `TAIWAN_EXPERT` | 全部 | `https://www.playsport.cc/billboard/mainPrediction` | **LIVE** | **YES** | 玩運彩排行榜前 15 名專家大神之暱稱、近期待遇、勝率、勝負場次。 |
| **Playsport 社群選票** | `TAIWAN_CROWD` | 全部 | `https://www.playsport.cc/predict/scale` | **LIVE** | **YES** | 各選項之大眾投票百分比（`consensus_ratio`）與投票總人數（`vote_count`）。 |
| **ESPN Scoreboard API** | `SCHEDULE` | MLB/NFL/NBA/足球 | `http://site.api.espn.com/apis/site/v2/sports/...` | **LIVE** | **YES** | 國際賽事官方排程、對戰名稱、比賽狀態（Scheduled/In Progress/Final）。 |
| **Pybaseball** | `FOREIGN_PREDICTION` | MLB | `github.com/jldbc/pybaseball` (v2.2.7) | **PARTIAL** | **YES** | 套件被 import 讀取版本號，但模型演算法為本機依賠率區間硬編碼得分之 Bill James 畢氏勝率。 |
| **Penaltyblog** | `FOREIGN_PREDICTION` | 足球 | `github.com/martineastwood/penaltyblog` (v1.12.2) | **PARTIAL** | **YES** | 套件被 import 讀取版本號，但模型演算法為本機硬編碼 xG (1.55/1.15) 之 Scipy 泊松分佈。 |
| **TaiwanLottery 官網** | `TAIWAN_BETTING_MARKET` | 全部 | `sportslottery.com.tw` | **DEAD** | **NO** | 官方網站前置 Cloudflare WAF，回傳 403，無公開 API，生產路徑未使用。 |

---

# 7. Taiwan GitHub / Open Source Research Result

目前專案調研過之台灣相關開源專案真實狀態如下：

1. **`CharlieAlex/Sports-Betting-Freerider`**
   - **URL**: `https://github.com/CharlieAlex/Sports-Betting-Freerider`
   - **Purpose**: 爬取 Playsport 專家主推與大眾預測比例，串接 Line Bot。
   - **Stars**: 12 | **Last update**: 2024 | **License**: MIT
   - **Can run**: 可參考其爬蟲請求與 HTML 結構。
   - **Integrated**: **架構與思維借鑑（非直接 Import）**。
   - **What was reused**: 重寫為 `PlaysportScraper`，解析其 `scale` 與 `billboard` 端點。
   - **Reason if rejected**: 原專案為 Line Bot 腳本，非模組化 Library，無法直接當套件依賴。
2. **`YuanData/MLB_python-Crawler_and_R-predictive-analysis`**
   - **URL**: `https://github.com/YuanData/MLB_python-Crawler_and_R-predictive-analysis`
   - **Purpose**: 爬取台彩 MLB 賠率並以 R 語言預測。
   - **Stars**: 5 | **Last update**: 2023 | **License**: Unlicense
   - **Can run**: 部分過期。
   - **Integrated**: **未整合**。
   - **What was reused**: 參考其台彩讓分（客 -1.5 / 主 +1.5）欄位清洗邏輯。
   - **Reason if rejected**: 預測部分採 R 語言編寫，維護停滯。
3. **`asadman1523/sportlotterycomtw_report`**
   - **URL**: `https://github.com/asadman1523/sportlotterycomtw_report`
   - **Purpose**: Chrome 擴充套件，匯出官網「我的投注」歷史損益。
   - **Stars**: 8 | **Last update**: 2024 | **License**: MIT
   - **Can run**: 可執行（瀏覽器外掛）。
   - **Integrated**: **未整合**。
   - **What was reused**: 參考其注單流水帳損益計算欄位定義。
   - **Reason if rejected**: 為 JavaScript Chrome Extension，非 Python 後端套件。
4. **`stu01509/TaiwanLotteryCrawler`**
   - **URL**: `https://github.com/stu01509/TaiwanLotteryCrawler`
   - **Purpose**: 台灣彩券（大樂透、威力彩）開獎爬蟲。
   - **Stars**: 85 | **Last update**: 2024 | **License**: MIT
   - **Integrated**: **未整合**。非運動彩券（Sports Lottery）。
5. **`ywchiu/largitdata`**
   - **URL**: `https://github.com/ywchiu/largitdata`
   - **Purpose**: 大數學堂爬蟲教學範例。
   - **Stars**: 150+ | **Last update**: 2022 | **License**: MIT
   - **Integrated**: **未整合**。純教學教材，借鑑其提取內嵌 JSON 概念。

**結論**：  
**目前沒有任何一個台灣專屬的開源 repo 是以第三方套件（pip package）的形式被本專案直接 import 執行。所有台灣相關邏輯均為專案自行撰寫之爬蟲適配層。**

---

# 8. Foreign GitHub Prediction Models

| Model | Repo | Sport | Output | Actually runs? | Adapter | Used by Signal Hub? |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: |
| **Pybaseball** | `jldbc/pybaseball` | MLB | 勝率機率 (`probability`)、市場優勢 (`edge`) | **部分執行 (讀取版本號)** | `PybaseballMLBAdapter` | **YES** |
| **Penaltyblog** | `martineastwood/penaltyblog` | 足球 | 期望勝率 (`probability`)、市場優勢 (`edge`) | **部分執行 (讀取版本號)** | `PenaltyblogSoccerAdapter`| **YES** |

### ⚠️ 極為重要之真實性揭露（Facade Reality）：
1. **`PybaseballMLBAdapter` 實際執行的代碼**：
   ```python
   # 程式碼真實片段 (integrations/models/pybaseball_mlb_model.py):
   if taiwan_odds <= 1.50:
       est_runs_for = 5.20; est_runs_against = 3.60
   elif taiwan_odds <= 1.80:
       est_runs_for = 4.80; est_runs_against = 4.20
   else:
       est_runs_for = 4.10; est_runs_against = 4.90

   rf_pow = est_runs_for ** 1.83
   ra_pow = est_runs_against ** 1.83
   pyth_win_prob = rf_pow / (rf_pow + ra_pow)
   ```
   **真相**：它**完全沒有呼叫 pybaseball 查詢任何大聯盟球隊戰績、球員打擊率或 Statcast 數據**！它只是讀取了 `pybaseball.__version__`，然後**直接把台灣運彩賠率當輸入**，用 3 段 if-else 硬編碼出得分期望，再套用畢氏勝率公式。
2. **`PenaltyblogSoccerAdapter` 實際執行的代碼**：
   ```python
   # 程式碼真實片段 (integrations/models/penaltyblog_soccer_model.py):
   home_xg = 1.55
   away_xg = 1.15
   for h in range(8):
       for a in range(8):
           p = float(poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg))
   ```
   **真相**：它**完全沒有呼叫 penaltyblog 的 Dixon-Coles 回歸模型**，也沒有傳入任何足球隊伍數據。它對**全世界每一場足球賽**，都硬編碼主隊 xG = 1.55、客隊 xG = 1.15，然後用 `scipy.stats.poisson` 計算泊松機率。

**審查結論**：目前國外開源模型實質上是 **「名義上依賴開源套件，實際上執行硬編碼啟發式規則的偽裝層（Facade）」**。

---

# 9. Signal Hub — 現在到底怎麼算？

### 完整決策邏輯 Pseudo-code (`core/signal_hub.py`)：

```python
def evaluate_taiwan_leg(leg):
    signals = []
    external_supports = 0

    # 1. 台灣盤口訊號 (BETTING_MARKET)
    odds = leg.taiwan_odds
    market_implied = 1.0 / odds
    # 只要賠率 <= 1.85 或 隱含勝率 >= 50%，視為盤口支持
    if market_implied >= 0.50 or odds <= 1.85:
        external_supports += 1

    # 2. 玩運彩殺手大神訊號 (EXPERT)
    # 啟發式合成規則：如果賠率 <= 2.20 且大眾選票比例 >= 60%
    if leg.taiwan_odds <= 2.20 and leg.signal_evidence.consensus_ratio >= 0.60:
        top_expert = get_billboard_top_ranker() # e.g. "社會我瓜哥", 94%
        signals.append(PredictionSignal(type="EXPERT", score=top_expert.winpercentage))
        external_supports += 1

    # 3. 彩迷社群選票訊號 (CROWD)
    crowd_pct = leg.signal_evidence.consensus_ratio * 100
    if crowd_pct >= 58.0:
        external_supports += 1

    # 4. 開源模型訊號 (MODEL - Pybaseball / Penaltyblog)
    for model_sig in run_models(leg):
        if model_sig.probability >= 0.52 or model_sig.edge >= 0.0:
            external_supports += 1

    # 最終一致度判定 (Agreement Level)
    if external_supports >= 3:
        agreement = "HIGH"       # 🟢 HIGH
    elif external_supports == 2:
        agreement = "MED"        # 🟡 MED
    else:
        agreement = "INSUFFICIENT_SIGNAL" # ⚪ INSUFFICIENT
```

### 評判指標說明：
- **🟢 HIGH 是由什麼造成？**  
  `external_supports >= 3`。通常發生在「熱門低賠標的（賠率 <= 1.85 盤口算 1 票）」+「大眾選票 >= 58%（算 1 票）」+「大眾選票 >= 60% 且賠率 <= 2.20 觸發大神合成（算 1 票）」+「模型因為低賠估出高勝率（算 1 票）」，共 4 票中取得 3 票以上。
- **🟡 MED 是什麼？**  
  `external_supports == 2`。例如盤口低賠（1 票）加上模型支持（1 票），但大眾選票不足 58%。
- **⚪ INSUFFICIENT 是什麼？**  
  `external_supports <= 1`。通常是高賠冷門（賠率 > 1.85 盤口不投），大眾選票也不看好，缺乏外部支撐。
- **是否存在統計校準或動態權重？**  
  **完全沒有**。沒有校準機率（Calibrated Probability），沒有貝氏更新，沒有邏輯迴歸，純粹是**寫死門檻的多數決計票法（Heuristic Threshold Voting）**。

---

# 10. Give Me One Real Example

以下為 2026-09-18 於本機 Python 3.11 實際連線執行的真實運彩選項資料：

```text
Sport: baseball
League: MLB
Event: 台灣運彩賽事編號 #125 【小熊 (客) vs Cincinnati (主)】 (網頁文字切詞為 "小熊 vs Clay")
Taiwan market: 不讓分
Selection: 小熊 不讓分勝 (1.52)
Taiwan odds: 1.52

Schedule source: 
  - Source: ESPN Scoreboard API (http://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard)
  - Raw Event: "Chicago Cubs at Cincinnati Reds"
  - Scheduled Date: 2026-09-18T22:40Z
  - Match Status: Scheduled

Taiwan expert source:
  - Source: playsport.cc/billboard/mainPrediction?allianceid=1
  - Ranker: 榜首大神【社會我瓜哥】 (月勝率 94.0%, 17勝 1敗)
  - Synthesized Pick: 小熊 不讓分勝 (1.52) (因 odds=1.52<=2.2 且 crowd=72%>=60% 觸發合成)
  - Timestamp: 2026-09-18T17:48:42.024317+00:00

Taiwan crowd source:
  - Source: playsport.cc/predict/scale?allianceid=1
  - Vote Stats: 72.0% 支持率 (167 人預測)
  - Label: CROWD (HIGH Confidence)
  - Timestamp: 2026-09-18T17:48:42.024317+00:00

Foreign model A:
  - Model: Pybaseball Pythagorean Expectation (v2.2.7)
  - Output: 評估勝率 56.1% (對比台彩隱含機率 65.8%，優勢 -9.7pp)
  - Details: 依賠率 1.52 映射出預期得分 4.8 vs 4.2
  - Timestamp: 2026-09-18T17:48:42.024317+00:00

Foreign model B:
  - Model: Penaltyblog Soccer Poisson (v1.12.2)
  - Output: None (該模型僅適用於足球，棒球賽事自動略過)

Normalized signals:
  1. [BETTING_MARKET] 台彩盤口 1.52 ➔ 支持 (隱含勝率 65.8% >= 50%)
  2. [EXPERT] 玩運彩榜首大神 (社會我瓜哥) ➔ 支持 (歷史勝率 94%)
  3. [CROWD] 彩迷選票 72.0% ➔ 支持 (72% >= 58%)
  4. [MODEL] Pybaseball 畢氏勝率 56.1% ➔ 支持 (56.1% >= 52%)

Final Signal Hub output:
  - Agreement Level: 🟢 HIGH (4/4 支持)
  - Agreement Badge: 🟢 HIGH
  - Support Count: 4
```

---

# 11. Parlay Engine

### 1. Inputs
`ParlayEngine.search_parlays` 接收：
- `legs`: 經過 Signal Hub 評估過的 `TaiwanLeg` 物件清單。
- `min_odds`: 使用者設定之最低倍率（如 25.0）。
- `max_odds`: 使用者設定之最高倍率（如 75.0）。
- `min_legs`: 最小串關數（預設 2）。
- `max_legs`: 最大串關數（預設 6）。

### 2. Eligibility
- `leg.eligible_for_parlay == True`
- `leg.taiwan_odds > 1.0`（排除無效賠率）。

### 3. Taiwan odds
- **100% 使用台灣運彩實際賠率**。總倍率計算式為嚴格連乘：
  $$\text{Total Odds} = \prod_{i=1}^{k} \text{leg}_i.\text{taiwan\_odds}$$
  若連乘過程中超過 `max_odds` 即時 `break` 剪枝。

### 4. Target
使用者可在 UI 上自由設定 **10.0x ~ 500.0x**（提供 Radio 快捷選項與自訂 Slider 滑桿）。

### 5. Search algorithm
- **剪枝候選池**：為防組合爆炸，每場賽事依情報支援數與賠率排序，僅保留前 2 個最佳選項；全場次僅取前 16 場賽事。
- **暴力搜尋 (Brute Force Combinations)**：
  - 外層：`itertools.combinations(event_ids, num_legs)` 遍歷不重複的比賽組合。
  - 內層：`itertools.product(*leg_groups)` 遍歷各場次內入選的選項。

### 6. Cross-sport
**完全支援**。候選池可同時納入 MLB、英超足球、NFL 美足、CPBL 等，透過 `itertools.combinations` 自然混串。

### 7. Mutual exclusion (同場互斥過濾規則)
- **具體實作規則**：
  在遍歷時，組合的第一層是 `itertools.combinations(event_ids, num_legs)`，其中 `event_ids` 是每場比賽唯一的台彩賽事編號（`event_id`）。
  因此，任何生成的串關組合中，**絕對不會出現兩場相同 `event_id` 的選項**。
  （例如：同一張單內不可能同時出現「道奇客勝」與「道奇大 8.5」，100% 滿足台灣運彩單場不重複過關規定）。

---

# 12. Ranking Logic

當系統找到數百組符合倍率的串關時，如何排序誰排第一？

在 `core/parlay_engine.py` 第 173~175 行：

```python
# 1. 🟢 共識較高 (high_consensus)
high_consensus.sort(
    key=lambda x: (x["avg_support"], -abs(x["total_odds"] - (min_odds + max_odds)/2)), 
    reverse=True
)

# 2. 🟡 比較瘋 (aggressive)
aggressive.sort(
    key=lambda x: (x["avg_support"], x["total_odds"]), 
    reverse=True
)

# 3. 🔴 極限 Moonshot (moonshot)
moonshot.sort(
    key=lambda x: x["total_odds"], 
    reverse=True
)
```

### 關鍵審查問題解答：
### 是否存在「高倍率但資料差」反而排在「低一點但 evidence 好」前面的情況？
**答案：在 `moonshot` 桶中「確實存在」！**
- 在 `high_consensus` 與 `aggressive` 桶中，第一排序欄位是 `avg_support`（平均情報支援度），因此 evidence 好的注單會排在前面。
- 但在 `moonshot` 桶中，排序 key 只有 `x["total_odds"]`！這意味著在 Moonshot 模式下，**一組 480 倍但全都是 ⚪ INSUFFICIENT 缺乏依據的注單，會排在 220 倍但有 🟢 HIGH 情報支持的注單前面**。

---

# 13. Wallet Current Logic

本地 SQLite 狀態機以 `WeeklyWalletManager` 為核心，每週上限 `WEEKLY_PLAY_CAP = 200.0`。

### Case A: Prize Pool = 0，新週開始
- `old_wallet = 0`, `prize_pool = 0`
- `draw_from_prize = 0` ➔ `new_wallet = 0`
- `shortfall = 200 - 0 = 200`
- `external_deposit_remaining = 200.0`
- **狀態**：使用者可從自備外部現金補入最多 NT$ 200。

### Case B: Prize Pool = 70，新週開始
- `old_wallet = 0`, `prize_pool = 70`
- `needed = 200 - 0 = 200`
- `draw_from_prize = min(200, 70) = 70`
- `prize_pool` 扣除 70 變為 0
- `new_wallet` 提撥變為 70
- `shortfall = 200 - 70 = 130`
- `external_deposit_remaining = 130.0`
- **狀態**：新週錢包已有 NT$ 70（來自保留池滾存），外部現金最多只允許再補 NT$ 130。

### Case C: Prize Pool = 5000，新週開始
- `old_wallet = 0`, `prize_pool = 5000`
- `needed = 200`
- `draw_from_prize = 200`
- `prize_pool` 變為 4800
- `new_wallet` 變為 200
- `shortfall = 200 - 200 = 0`
- `external_deposit_remaining = 0.0` (`can_deposit = False`)
- **狀態**：錢包自動從獲利池充盈 NT$ 200，**本週外部入金額度強制鎖定為 0，完全禁止自掏腰包**。

### Case D: 本週 Wallet 已經歸零（200 已下注），但 Prize Pool 還有 5000。是否可以當週再補？
### 驗證代碼：**絕對不可以。**
在 `WeeklyWalletManager.get_status()`：
- `wallet_balance = 0.0`, `weekly_staked = 200.0`
- `current_committed = wallet_bal + staked = 200.0`
- `shortfall = max(0.0, 200.0 - 200.0) = 0.0`
- `external_deposit_remaining = 0.0`
- 若使用者試圖呼叫 `deposit_external()`，第 177 行強制拋出：`ValueError("【入金上限攔截】本週外部入金額度剩餘 NT$ 0.00... 風控鐵律：每週最多只允許 NT$ 200 進入戰場！")`。
- 若使用者想從 Prize Pool 調錢：系統中從 Prize Pool 提撥至 Wallet 的唯一邏輯在 `_ensure_week_initialized()`，**該函式只有在跨週（`current_week != now_week`）時才會執行**，無任何當週提撥接口。
- **結論**：錢包歸零後，**當週嚴格鎖死，必須等待下週刷新**。

---

# 14. Ticket Lifecycle

```text
[候選注單 Candidate] (ParlayEngine 產出)
        ↓
[使用者勾選與設定注金 Selected] (預設 NT$ 20)
        ↓ (點擊「📝 確認下注」按鈕)
[下注成立 Placed / Open]
   • 呼叫 WeeklyWalletManager.stake_bet(stake) 扣減本週可玩餘額
   • 寫入 SQLite tickets 表，狀態設為 'OPEN'
        ↓
[賽事等待中 Pending] (無自動開獎輪詢，等待比賽打完)
        ↓ (使用者於 TAB 3 手動點擊)
   ┌────┴───────────────────────────┐
   ↓                                ↓
[點擊 🎉 恭喜中獎]             [點擊 ❌ 標記未過關]
   • 狀態更新為 'WON'             • 狀態更新為 'LOST'
   • actual_payout = 預期派彩     • actual_payout = 0.0
   • 自動呼叫 credit_winnings()   • 錢包餘額與保留池維持不變
   • 派彩 100% 鎖入 Prize Pool
```

### 關鍵審查問題解答：
- **現在下注是不是人工確認？**：**是**。使用者必須在 Streamlit UI 上手動點擊「📝 確認下注」。
- **系統是否真的幫使用者自動下注？**：**否**。台灣運彩官網有 Cloudflare WAF 與驗證碼，且無官方投注 API。系統僅作本機記帳，使用者須拿著注單資訊自行去實體投注站或官網手動下注。
- **比賽結果是否自動更新？**：**否**。目前無賽果自動結算 Worker，必須由使用者在 TAB 3 的未結算清單中，手動點選中獎或未中獎按鈕。
- **Payout 是否自動算？**：**是**。依下注金額 $\times$ 總賠率自動計算至小數點後兩位。
- **Void（退盤/無效）如何處理？**：SQLite 表雖定義了 `'VOID'` 狀態約束，但 **UI 上目前沒有提供 Void 按鈕**。若比賽取消，目前只能手動進資料庫修改，或選中獎並手動填自訂金額。

---

# 15. UI / UX Current State

Streamlit 目前採用單頁三頁籤（3 Tabs）設計：

### Header & Banner
- **User sees**: 標題「🐕 台灣運彩「瘋狗流」決策系統」、資料連線狀態 Ribbon、四個置頂資金指標（本週可玩餘額、本週已下注、累積獲利保留池、本週外部補金）。
- **Live data**: 即時 SQLite 資金數據。

### Tab 1: 今日可玩 (賽季雷達)
- **User sees**: 9 個聯賽的 🟢/🟡/🔴 燈號卡片與開盤場次；點擊聯賽 Expanders 可查看今日對戰隊伍與台彩盤口賠率。
- **User can click**: 「🔄 刷新即時盤口」按鈕、各聯賽詳細對戰展開面板。
- **Live data**: Playsport 即時盤口賽事與賠率、ESPN 賽程。
- **Known limitations**: 隊名有時截斷不佳（把投手名當隊名）；無開賽倒數計時。

### Tab 2: 瘋狗看盤 (10~500倍 串關 & Signal Hub)
- **User sees**:
  - 目標倍率單選（10~25x, 25~75x, 75~200x, 200~500x 或自訂滑桿）。
  - 運動賽事混串勾選框。
  - 注金輸入框（預設 NT$ 20，最大限制不超過錢包可玩餘額）。
  - 風格切換單選（🟢 共識較高 / 🟡 比較瘋 / 🔴 極限 Moonshot）。
  - 串關卡片清單、各關卡表格、**「🔍 為什麼推薦這組？點擊查看各關卡完整證據抽屜 (Why Drawer)」**。
- **User can click**: 風格單選切換、展開 Why 抽屜、各串關卡片底部的「📝 確認下注」按鈕。
- **Live data**: 串關總倍率（100% 台彩實際盤口）、大眾投票數據、排行榜殺手資料。
- **Mock / Heuristic data**: 開源模型輸出的機率是 Facade 硬編碼計算；大神主推是依門檻自動貼上的。

### Tab 3: 資金紀錄 (每週 NT$200 錢包與戰績)
- **User sees**: 外部現金補金控制台、獲利池提領控制台、進行中未結算注單清單、歷史已結算注單表格（含淨損益）。
- **User can click**:
  - 「確認補金入錢包」按鈕。
  - 「確認提領獲利」按鈕。
  - 各未結算注單的「🎉 恭喜中獎！」按鈕（觸發氣球特效與派彩入池）。
  - 各未結算注單的「❌ 標記未過關」按鈕。
- **Live data**: SQLite 內儲存的真實帳本流水與注單紀錄。
- **Known limitations**: 無法取消注單（無 Void 按鈕）；無圖表可視化資金曲線。

---

# 16. Tests — Unit vs Real Integration

目前 test suite 共有 17 個測試用例，分類如下：

| Test Name | File | Type | Uses Mock? | What does it prove? | What does it NOT prove? |
| :--- | :--- | :---: | :---: | :--- | :--- |
| `test_end_to_end_real_day_pipeline` | `tests/integration/test_end_to_end_real_day.py` | **Live E2E** | **NO** | 證明從連線 Playsport 抓真實盤口、雷達判斷、SignalHub 豐富化、ParlayEngine 搜尋到錢包下注中獎的全流程代碼無語法崩潰。 | 不保證預測模型數據的真實度（模型吃硬編碼）；不證明下注能送入台彩官網。 |
| `test_live_odds_source` | `tests/integration/test_live_odds_source.py` | **Live Integration** | **NO** | 證明 Playsport 爬蟲能即時連線抓取台灣運彩 MLB 盤口，且賠率大於 1.0。 | 不證明其他冷門聯賽也能 100% 成功解析。 |
| `test_live_expert_source` | `tests/integration/test_live_expert_source.py` | **Live Integration** | **NO** | 證明 Playsport Billboard 爬蟲能即時連線抓取排行榜前 15 名殺手資料。 | 不證明抓取到了大神具體買了哪場比賽。 |
| `test_live_espn_schedule_provider` | `tests/integration/test_live_schedule_provider.py`| **Live Integration** | **NO** | 證明 ESPN 公開 Scoreboard REST API 連線正常，能回傳今日賽程。 | 不證明賽程能跟台彩賽事自動對齊。 |
| `test_github_model_adapter` (2 tests) | `tests/integration/test_github_model_adapter.py` | **Unit / Adapter** | **YES (Mock Leg)** | 證明 `pybaseball` 與 `penaltyblog` 模組能被匯入，且 adapter 能在輸入 Leg 後回傳合法機率。 | **不證明模型使用了真實隊伍歷史數據**（本測試僅驗證寫死數值的公式運算）。 |
| `test_signal_data_lineage` | `tests/integration/test_signal_data_lineage.py` | **Unit / Lineage** | **YES (Mock Leg)** | 證明 `SignalHub` 能正確組裝各適配器輸出的欄位標籤與 confidence。 | 不證明各情報來源間存在統計獨立性。 |
| `test_season_radar_lights` | `tests/test_v3_system.py` | **Unit** | **YES (Mock Matches)**| 證明雷達的三色燈規則在有/無賽事時的邏輯分支正確。 | 不證明即時爬蟲解析網頁的能力。 |
| `test_signal_hub_consistency` | `tests/test_v3_system.py` | **Unit** | **YES (Mock Options)**| 證明計票法在不同門檻下能正確輸出 HIGH / LOW 一致度。 | 不證明機率的客觀校準性。 |
| `test_parlay_engine_bounds` | `tests/test_v3_system.py` | **Unit** | **YES (Mock Matches)**| 證明 `ParlayEngine` 能在給定邊界內過濾倍率，且保證同場賽事不重複。 | 不證明在大規模賽事池下的效能上限。 |
| `test_weekly_wallet_flow` (3 tests) | `tests/test_v3_system.py` | **Unit** | **NO (Temp SQLite)** | 證明每週 NT$200 限額、Prize Pool 鎖定、跨週優先自保留池滾存之狀態機 100% 正確。 | 不證明真實金融帳戶出入金。 |
| `test_ticket_recorder_lifecycle` | `tests/test_v3_system.py` | **Unit** | **NO (Temp SQLite)** | 證明注單從 OPEN 到 WON/LOST 結算與帳本記錄之完整資料庫生命週期。 | 不證明自動對獎能力。 |
| `test_engine` (4 tests) | `tests/test_engine.py` | **Unit (Legacy)** | **YES (Mock Matches)**| 驗證舊版 `WarChestManager`, `TicketManager`, `ParlayOptimizer` 的歷史邏輯。 | 與目前主應用程式 `app.py` 的運行路徑無關。 |

---

# 17. Current Mock / Placeholder Inventory

在目前生產路徑中存在的假資料、寫死常數與啟發式預設值清單：

| Location | Placeholder / Hardcoding | Why it exists | Is it reachable in normal UI? |
| :--- | :--- | :--- | :---: |
| `core/scraper.py` (`_fallback_matches`) | 硬編碼的道奇 vs 巨人賽事（`FB_1_101`，賠率 1.45/1.75） | 網路斷線或 Playsport 改版時的最後降級備援 | **條件觸發**（僅在無網路且無本機快取時可見） |
| `integrations/models/pybaseball_mlb_model.py` (L44-52) | 依賠率 <=1.50, <=1.80, >1.80 寫死預期得分 (5.2/3.6, 4.8/4.2, 4.1/4.9) | 未串接 pybaseball 真實球隊打擊/投球數據庫之臨時替代品 | **常態觸發**（所有 MLB 賽事模型評估皆使用此寫死值） |
| `integrations/models/penaltyblog_soccer_model.py` (L43-44) | 寫死主隊 xG = 1.55，客隊 xG = 1.15 | 未串接 penaltyblog 歷史聯賽積分與 Dixon-Coles 訓練之臨時替代品 | **常態觸發**（所有足球賽事模型評估皆使用此寫死值） |
| `integrations/experts/playsport_expert.py` (L46) | 若賠率 <= 2.20 且大眾選票 >= 60%，直接掛上排行榜榜首大神之勝率與名字 | 爬蟲未實作「抓取個別專家投注明細頁」之替代 Heuristic | **常態觸發**（所有符合門檻之賽事皆會被掛上此合成大神） |
| `core/season_radar.py` (`LEAGUES` 常數) | 寫死各運動聯賽的預設賽季月份（如 MLB 為 3~11 月） | 離線判斷休賽季的粗略日曆依據 | **常態觸發**（無開盤賽事時作為黃燈/紅燈依據） |
| `core/scraper.py` (`ALLIANCE_MAP`) | 寫死聯盟代碼對應字典（1->MLB, 4->足球等） | 玩運彩網站內部代碼對應 | **常態觸發** |

---

# 18. Failure Modes

| 故障情境 | 系統反應機制 (System Behavior) | 最終產品狀態 |
| :--- | :--- | :---: |
| **台灣盤口來源 (Playsport) 掛掉 / 403 / 改版** | 1. 捕捉 HTTP 異常，記錄 Warning。<br>2. 優先嘗試載入 `data/cache/` 內的過期快照（Stale Snapshot）。<br>3. 若本機無快照，載入 `_fallback_matches`。<br>4. 頁面不會白屏或崩潰，但盤口會退回快照或寫死資料。 | **FALLBACK (降級運行)** |
| **Playsport 大神排行榜掛掉** | 1. `fetch_expert_leaderboard` 捕捉異常回傳空清單 `[]`。<br>2. `PlaysportExpertAdapter` 回傳 `None`。<br>3. Signal Hub 將專家欄位標記為「無大神主推記錄」，support 數不計此項。 | **DISABLE SOURCE (靜默停用)** |
| **國外開源模型掛掉 / 算式報錯** | 1. `ModelRegistry.evaluate_leg_across_models` 設有 `try-except`。<br>2. 該模型信號被丟棄，記錄 Warning。<br>3. Signal Hub 標記「純盤口評估」，降級為 2 票或 1 票。 | **DISABLE SOURCE (局部降級)** |
| **ESPN 賽程排程 Provider 掛掉** | 1. `ESPNScheduleAdapter` 捕捉連線異常回傳 `[]`。<br>2. Season Radar 檢測到 `espn_event_count == 0`。<br>3. 自動退回以月份日曆（`in_season_calendar`）與台彩實際盤口數作為判定基準。 | **FALLBACK (日曆降級)** |
| **SQLite 帳本鎖定或檔案損壞** | 1. SQLite 拋出 OperationalError。<br>2. Streamlit 介面彈出 `st.error` 紅色警告方塊。<br>3. 阻止本次下注或入金寫入，保護帳本一致性。 | **CRASH SHIELD (安全攔截)** |

---

# 19. Current Data Flow Diagram

```text
       [Playsport HTML / Scale]               [ESPN REST API]
                  │ (LIVE / CACHE)                  │ (LIVE)
                  ▼                                 ▼
       PlaysportOddsAdapter               ESPNScheduleAdapter
                  │                                 │
                  ▼                                 ▼
          [List of TaiwanLeg] ────────────► SeasonRadar (🟢/🟡/🔴)
                  │                                 │
                  │ (LIVE)                          ▼
                  │                        Streamlit Tab 1 (雷達展示)
                  ▼
              Signal Hub
                  │
  ┌───────────────┼───────────────────────────────┐
  │ (LIVE)        │ (HEURISTIC)                   │ (HARDCODED / FACADE)
  ▼               ▼                               ▼
Playsport     Playsport Expert                ModelRegistry
Crowd         Billboard Adapter           ┌───────┴────────┐
Adapter       (榜首名單+門檻合成)           ▼                ▼
  │               │                 PybaseballMLB    PenaltyblogSoccer
  │               │                 (寫死得分推算)   (寫死1.55/1.15 xG)
  └───────────────┼───────────────────────┘                │
                  ▼                                        │
           Enriched TaiwanLeg (含 🟢/🟡/⚪ 一致度) ◄───────┘
                  │
                  │ (LIVE 記憶體物件傳遞)
                  ▼
            Parlay Engine (10x~500x 搜尋)
                  │ (itertools 組合 + 100% 台彩賠率連乘)
                  ▼
          3 Buckets 串關候選組合
                  │
                  ▼
       Streamlit Tab 2 (瘋狗看盤 & Why 抽屜)
                  │
                  │ (使用者點擊下注 - 人工觸發)
                  ▼
            TicketRecorder
                  │ (LIVE 本機事務)
                  ▼
          WeeklyWalletManager
                  │
                  ▼
       [data/war_chest.sqlite3] (錢包 / 獲利保留池 / 帳本 / 注單)
                  │
                  │ (使用者手動點擊中獎 - 人工結算)
                  ▼
       Streamlit Tab 3 (資金與戰績結算)
```

---

# 20. Current Product Maturity Assessment

| 維度 (Dimension) | 成熟度評級 (Status) | 現實客觀佐證 (Evidence) |
| :--- | :---: | :--- |
| **Taiwan market ingestion** | **Functional prototype** | 已能透過 Playsport 即時爬取完整讓分、不讓分、大小與實際賠率；但前置有快取依賴且隊名偶有切詞瑕疵。 |
| **Schedule awareness** | **Functional prototype** | 已整合 ESPN Scoreboard 公開 API，能即時掌握美職、美足與歐洲聯賽排程，但未與台彩賽事實體對齊。 |
| **Taiwan GitHub reuse** | **Partial** | 僅吸收借鑑 `Sports-Betting-Freerider` 爬蟲思路與 `YuanData` 欄位概念，未直接重用現有套件。 |
| **Foreign model integration** | **Placeholder** | 雖然在虛擬環境中安裝了 `pybaseball` 與 `penaltyblog`，但實際執行是依賠率硬編碼數值的 Facade。 |
| **Signal quality** | **Partial** | 具備真實盤口與社群大眾選票；但「專家」為門檻合成，「模型」為寫死公式，本質為粗略計票法。 |
| **Parlay search** | **Production-ready** | 100% 以台彩賠率連乘，嚴格落實同場互斥，剪枝與 10~500x 區間搜尋流暢，演算法邏輯完整。 |
| **Wallet** | **Production-ready** | 每週 NT$200 上限、獲利全數鎖定至保留池、新週自動自保留池提撥滾存之 SQLite 狀態機運作嚴密。 |
| **Ticket settlement** | **Functional prototype** | 支援注單生命週期儲存與手動開獎派彩，但無自動抓取官方比分自動結算的能力。 |
| **Live E2E** | **Functional prototype** | 今日真實賽事实測可一鍵完成抓盤、研判、組單、扣款與派彩，但全依賴人工在 UI 上點擊推進。 |
| **UI** | **Functional prototype** | Streamlit 三頁籤與 Why 抽屜互動流暢美觀，但欠缺 Void 退盤按鈕與賽事即時比分看板。 |

---

# 21. What You Would Do Next (Top 5 Gaps)

依審查重要性與產品邁向真正的 Goal 排序之 5 大核心落差：

### Gap 1: 開源統計模型實質為硬編碼 Facade，未真正使用球隊數據
- **Why it matters**: 目前 `Pybaseball` 與 `Penaltyblog` 只是在讀版本號，運算邏輯是寫死常數。這使得 Why 抽屜中的「開源模型評估」失去統計說服力，本質上只是對台彩盤口賠率的另類數學換算。
- **Recommended next action**: 
  1. 建立真正的球隊對照字典（如 `小熊 -> CHC`, `紅人 -> CIN`）。
  2. 呼叫 `pybaseball.team_batting()` 與近期先發投手數據，代入真實團隊得失分期望值。
  3. 呼叫 `penaltyblog.models.DixonColes`，傳入聯賽近期比分進行真實模型推論。

### Gap 2: 玩運彩「大神主推」為啟發式合成，非專家真實下注
- **Why it matters**: 目前的大神推薦是「只要大眾選票 >= 60% 且賠率 <= 2.2 就自動貼上榜首專家名字」，不是該專家真正看好這場比賽，存在嚴重的資訊不透明與虛假歸因風險。
- **Recommended next action**: 
  1. 爬取 Playsport 大神具體的主推清單（例如解析個別高手的主推頁或公開推薦文章）。
  2. 若無法取得該專家在該場比賽的真實下注，應誠實標記為「該專家今日未對本場發表推薦」，絕不進行自動合成。

### Gap 3: 缺少賽事实體對齊（Event & Team Canonical Identity）
- **Why it matters**: 目前隊名切割採粗暴的空白截斷，導致將投手名誤切為隊名（如 Cincinnati Reds 變成 "Clay"），且台彩賽事與 ESPN 賽事處於平行時空無法關聯，限制了後續自動抓比分與進階情報對接。
- **Recommended next action**: 
  建立 `TeamAliasManager` 與標準化正規化字典，將中英文隊名、簡稱、ESPN Slug 與台彩編號綁定為統一的 Canonical Match ID。

### Gap 4: 比賽結果與注單派彩全靠人工點擊，無自動結算機制
- **Why it matters**: 使用者下注後，隔天必須手動一場一場核對賽果並手動點擊「恭喜中獎」，極易發生人為誤點或作弊，失去決策台自動化與客觀紀律追蹤的價值。
- **Recommended next action**: 
  在 `ESPNScheduleAdapter` 擴充抓取 `status == "Final"` 的完賽比分，實作後台定時結算 Worker，自動比對注單盤口並結算派彩入 Prize Pool。

### Gap 5: 官方投注站無直接串接（Auto-Betting Placement）
- **Why it matters**: 決策台產出 10~500 倍神單後，使用者仍須手動至實體投注站或在有嚴格驗證碼的台彩官網手動點選，無法做到「一鍵下注」。
- **Recommended next action**: 
  先實作「台彩投注單 QR Code 生成器」（產生符合台彩實體機台掃描的投注 QR Code），使用者持手機至投注站一秒掃碼出單；遠期再評估 Headless 瀏覽器官網自動化方案。

---
*(本報告結束，全篇內容已如實反映目前 Codebase 真實狀態，供 Reviewer 進行架構與產品方向審查。)*
