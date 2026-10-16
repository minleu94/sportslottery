# 資料儲存架構與 C 槽 SSD 防磨損機制

本文件記錄專案在資料儲存架構、SSD 壽命防護、目錄映射（Junction）以及 Windows 定期排程上的實施細節。

---

## 1. 背景與設計初衷 (Problem Statement)

本專案內建一套自動化的運彩量化研究流水線（Research Pipeline），預設每 15 分鐘在背景執行一次：
- 自動爬取玩運彩各大聯盟賠率與專家主推
- 賽前 60 分鐘內凍結預測快照（Point-in-Time Snapshots）
- 運算數萬個組合以產生高倍串關候選（Parlay Candidates）
- 賽後對照官方賽果進行無偏結算並累積週報

由於高頻排程累積的數據量相當龐大（例如：`parlay_snapshots.jsonl` 已超過 600 MB，`prediction_snapshots.jsonl` 超過 80 MB，MLB 賽程底冊約 53 MB），若直接持續寫入作業系統所在的 **C 槽 SSD**，會迅速消耗快閃記憶體的寫入壽命（TBW）並佔用系統碟寶貴空間。

因此，系統實施了**「實體數據外移至 F 槽 ＋ C 槽 NTFS Junction 映射」**的完整防護架構。

---

## 2. 實體資料遷移與存放結構

目前所有動態產生、日誌、爬蟲快取與 SQLite 資料庫均已完全搬遷至：
**`F:\Min\Python\Project\SportsLottery_Data\`**

### 資料目錄拆解：
```text
F:\Min\Python\Project\SportsLottery_Data\
├── war_chest.sqlite3                  # 投注紀錄與 NT$200 風控錢包 SQLite 資料庫
├── research_pipeline/                 # 每 15 分鐘排程的主要數據池
│   ├── historical/
│   │   ├── parlay_snapshots.jsonl     # 高倍串關歷史紀錄 (>600 MB)
│   │   ├── prediction_snapshots.jsonl # 賽前凍結預測快照 (>80 MB)
│   │   └── odds_history.jsonl         # 盤口賠率變動走勢
│   ├── model_state/
│   │   ├── live_mlb_elo.json          # MLB 官方賽果即時 Elo 戰力
│   │   ├── mlb_official_schedule_ledger.json # MLB 歷年賽程與賽果帳本 (53 MB)
│   │   └── soccer_data_refresh.json   # 足球歷史對戰數據快取狀態
│   ├── runs/                          # 各次排程執行的詳細日誌與暫存
│   ├── reports/                       # 每週產生的量化模型驗證報表 (MD & JSON)
│   ├── operations/                    # 排程警報與事件狀態
│   └── logs/                          # 背景執行日誌文字檔
├── cache/                             # 外部來源爬蟲即時快取
├── snapshots/                         # 盤口切片備份
└── source_health/                     # 外部網站連線健康歷史
```

---

## 3. Windows Directory Junction（目錄交會點）防磨損原理

為了相容歷史代碼與預設路徑，避免修改底層路徑破壞原有邏輯，專案在 C 槽專案根目錄建立了 Windows NTFS 原生交會點（Directory Junction）：

```cmd
cmd /c mklink /J "C:\Projects\PythonProjects\sportslottery\data" "F:\Min\Python\Project\SportsLottery_Data"
```

### 運作機制與特點：
1. **0 KB 虛擬指針**：在 C 槽專案目錄看到的 `data` 只是一個 NTFS 系統標籤（Reparse Point），大小為 0 位元組，不佔用任何 C 槽實體容量。
2. **硬體層面重定向**：任何程式（無論是 Python、批次檔還是命令提示字元）存取 `C:\Projects\PythonProjects\sportslottery\data\...` 時，Windows 檔案系統核心會自動將所有 I/O 操作直接轉發至 F 槽。
3. **C 槽 0 實體寫入**：實際的快閃記憶體晶片擦除與寫入 100% 發生在 F 槽硬碟上，**C 槽維持 0 寫入**，徹底消除了頻繁快照帶來的 SSD 壽命耗損顧慮。

---

## 4. 集中管理模組與設定檔

專案引進了專門的儲存管理中樞，確保路徑調整具備高度靈活性：

1. **設定檔**：[`config/storage_config.yaml`](../config/storage_config.yaml)
   ```yaml
   data_root: F:/Min/Python/Project/SportsLottery_Data
   database_file: F:/Min/Python/Project/SportsLottery_Data/war_chest.sqlite3
   research_pipeline_root: F:/Min/Python/Project/SportsLottery_Data/research_pipeline
   ```
2. **核心模組**：[`core/storage_config.py`](../core/storage_config.py)
   - 提供 `get_storage_root()`、`get_db_path()`、`get_research_root()` 等標準取用介面。
   - 內建 `get_storage_stats()` 監控磁碟空間與各類快照容量。
   - 內建 `update_storage_location()`：可一鍵將整套資料遷移至任意新硬碟，並自動重新建立 Windows Junction 與更新排程參數。
3. **資料庫連線更新**：[`core/wallet.py`](../core/wallet.py) 與 [`core/war_chest.py`](../core/war_chest.py) 的預設資料庫路徑已改由 `get_db_path()` 動態提供，指向 F 槽。

---

## 5. 前端可視化設定介面

使用者可在 Streamlit 決策台的側邊欄開啟 **「⚙️ 系統設定與資料存放」** 頁面：
- **即時路徑與狀態**：顯示目前實體路徑與 C 槽防磨損保護狀態。
- **磁碟空間監控**：顯示目前磁碟（F 槽）剩餘容量、已使用百分比與詳細檔案大小。
- **動態變更路徑**：允許在介面上輸入任意新資料夾（支援勾選自動遷移現有資料），點擊即可一鍵換碟。
- **排程管理與 FAQ**：即時查看 Windows 排程狀態，提供一鍵啟用/停用按鈕，並說明排程的「滾動更新 vs 策略凍結」量化機制。

---

## 6. 排程靜默執行防護 (CREATE_NO_WINDOW)

排程在背景以 `pythonw.exe` 執行時，若呼叫外部 Console 指令（如 Git 版本檢查）而未帶有特化旗標，Windows 會強制為其建立 conhost/cmd 黑色命令提示字元視窗，造成螢幕上頻繁瞬間閃出黑視窗。

### 解決方案：
已在 [`core/strategy_version.py`](../core/strategy_version.py)、[`core/research_operations.py`](../core/research_operations.py)、[`core/research_alerts.py`](../core/research_alerts.py) 以及 [`core/storage_config.py`](../core/storage_config.py) 中全面套用：

```python
creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
subprocess.run([...], creationflags=creationflags)
```

此旗標徹底杜絕了任何控制台視窗的建立，確保 Windows 排程在背景執行時 100% 靜默無感。
