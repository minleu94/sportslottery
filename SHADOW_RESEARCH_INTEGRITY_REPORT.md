# SHADOW RESEARCH INTEGRITY REPORT

**Report Status**: **`CERTIFIED_FORWARD_READY`**  
**Strategy Version**: `v1.0-live`  
**Certification Date**: 2026-09-18  
**Repository**: `C:\Projects\PythonProjects\sportslottery`  
**Execution Environment**: Python 3.11.9 / Windows 11  

---

## 1. Executive Certification Matrix

本報告對台灣運彩智能決策系統在進入未來 30~60 天前瞻資料收集前，進行最終研究真實性、時間穿越防範與結算規則審查。

| 審查維度 (Integrity Dimension) | 驗證標準與防禦機制 | 審查結果 |
| :--- | :--- | :---: |
| **1. Prediction immutability (預測不可變性)** | 每一筆快照強制計算 SHA-256 `prediction_payload_hash`。結算時自動比對雜湊，若原始預測欄位有任何更動立即拋出 `AuditFailureError` 阻斷。 | **PASS** |
| **2. Pre-game cutoff integrity (開賽前截點完整性)** | 強制檢驗 `snapshot_timestamp < event_start`、`odds_timestamp < event_start`；開賽後資料強制標記 `POST_START_DATA` 並剔除於前瞻指標外。 | **PASS** |
| **3. Closing odds validity (真實關盤賠率有效性)** | 由獨立 `OddsWatcher` 紀錄時間序列，嚴格取賽前最後一筆有效賠率；若賽前無紀錄則誠實標為 `NOT_AVAILABLE`，絕不以預測賠率或賽後賠率造假。 | **PASS** |
| **4. Taiwan settlement rules (台灣運彩官方派彩規範)** | 完整實作 `TaiwanSettlementRules`：棒球含延長/平手VOID、足球嚴格90分鐘常規賽、過關中VOID腿賠率轉1.0重算總倍率，杜絕全單判負。 | **PASS** |
| **5. Duplicate protection (重複下注與多重計數防禦)** | 建立確定性 `parlay_fingerprint`；TOP_HIGH / TOP_MED / TOP_TARGET 若選出相同組合自動合併為 1 張注單（$N=1$），僅扣 1 次 NT$10 虛擬注金。 | **PASS** |
| **6. Snapshot idempotency (每日快照冪等性)** | 建立 `uniqueness_key = strategy:event:market:selection:date`；同一天重複執行 `main.py snapshot` 自動略過，不產生重複預測。 | **PASS** |
| **7. Result provenance (賽果來源可溯性與衝突熔斷)** | 紀錄各賽果資料來源（MLB Stats API / ESPN / Football Data）；若來源間分數發生衝突，立即熔斷標記為 `UNRESOLVED`，嚴禁自行猜測。 | **PASS** |

### 最終審查判定：**`ALL CHECKS PASSED (FORWARD COLLECTION COMMENCED)`**

---

## 2. Detailed Technical Evidence

### 2.1 密碼學預測載荷雜湊 (Cryptographic Prediction Payload Hash)
- **演算法**: SHA-256
- **規範化序列化**: 排序所有鍵值（`sort_keys=True`），去除多餘空白（`separators=(',', ':')`）。
- **覆蓋欄位**: `snapshot_timestamp`, `event_id`, `event_start`, `sport`, `league`, `market`, `selection`, `side`, `line`, `taiwan_odds`, `odds_timestamp`, `market_implied_prob`, `crowd_ratio`, `crowd_votes`, `model_probability`, `model_market_delta_pp`, `evidence_quality`, `strategy_version`, `settlement_rule_id`。
- **竄改阻斷**: 結算模組呼叫 `settle_prediction()` 時，自動重算雜湊。若與快照原始存檔之 `prediction_payload_hash` 不符，系統拋出：
  $$\text{AuditFailureError: AUDIT\_FAILURE - Original prediction payload altered!}$$

### 2.2 關盤賠率與雙指標 CLV (True Closing Odds & Dual CLV)
- **檔案**: `data/historical/odds_history.jsonl`
- **關盤定義**: 賽前最後一筆觀測時間點 $\text{observed\_at} < \text{event\_start}$ 之台彩賠率。
- **雙重 CLV 指標計算**:
  1. 賠率倍率差（Odds CLV Ratio）:
     $$\text{CLV}_{\text{odds}} = \frac{\text{Odds}_{\text{prediction}}}{\text{Odds}_{\text{closing}}} - 1.0$$
  2. 隱含勝率位移點數（Probability Movement pp）:
     $$\Delta\text{pp}_{\text{CLV}} = \left(\frac{1}{\text{Odds}_{\text{closing}}} - \frac{1}{\text{Odds}_{\text{prediction}}}\right) \times 100.0$$
- **缺失防造假宣告**: 若無開賽前有效賠率點，`closing_odds = None`，`clv_status = NOT_AVAILABLE`，標記原因 `NO_CLOSING_ODDS`，嚴禁拿國外盤口或預測賠率替代。

### 2.3 台灣運彩官方派彩規範 (Taiwan Settlement Rules Engine)
- **檔案**: [`core/settlement/taiwan_rules.py`](file:///C:/Projects/PythonProjects/sportslottery/core/settlement/taiwan_rules.py)
- **棒球**: 含延長賽。若法定或延長結束仍為平手，不讓分玩法判定 `VOID`（退費/賠率 1.0）。讓分/大小剛好同分判定 `PUSH`（賠率 1.0）。
- **足球**: **嚴格以法定 90 分鐘加上傷停補時為準**，不含 30 分鐘延長賽與 PK 大戰。90 分鐘平手時僅「和局」中獎，客勝與主勝均判 `LOST`。
- **籃球與美足**: 含延長賽（Overtime）。
- **過關無效注項重算 (Parlay VOID Logic)**:
  串關單中任一腿因取消、延期或平手判定為 `VOID` / `PUSH` 時，**該腿賠率固定轉為 1.0**。若其餘腿全過，該單依重算後之總倍率派彩，絕不直接整張判負。

### 2.4 影子投資組合去重與樣本真實性 (Shadow Portfolio Deduplication)
- **指紋產生**: `parlay_fingerprint` 依排序後之注項要素計算 SHA-256。
- **去重實證**:
  若今日之 `TOP_HIGH` 與 `TOP_MED` 篩選出完全相同的 4 關組合：
  - 系統僅寫入 1 筆影子注單 ($N = 1$)。
  - 標記 `strategy_tags = ["TOP_HIGH", "TOP_MED"]`。
  - 虛擬扣款僅扣 NT$10（而非重複扣 NT$20 或 NT$30），防止虛胖樣本數與扭曲報酬率。

### 2.5 乾淨研究資料集匯出 (Data Research Clean Export)
- 匯出目錄: `data/research/`
  1. `single_leg_forward.csv`: 單場前瞻預測（含截點檢驗、雜湊、關盤賠率、CLV、排除原因）。
  2. `parlay_forward.csv`: 候選與影子串關單（含指紋、腿數、重算倍率、派彩、損益）。
  3. `source_metrics.csv`: 分組指標與小樣本標籤。

---

## 3. 凍結宣告與未來維護規範

1. **核心預測邏輯全面凍結**:
   - `STRATEGY_VERSION = "v1.0-live"`
   - 外部模型係數、Signal Hub 門檻、串關賠率搜尋規則、真實每週 NT$200 錢包**維持嚴格凍結**。
2. **正式開始 30 天實盤前瞻收集**:
   - 每日排程或手動執行：`python main.py snapshot`
   - 輕量盤口時序監控：`python main.py watch-odds`
   - 每日完賽結果結算：`python main.py settle`
   - 每週產出稽核報表：`python main.py weekly-report`
3. **首份前瞻驗證報告 (`FORWARD_VALIDATION_REPORT.md`) 啟動標準**:
   - 實盤資料收集滿 30 天，或累積已結算合格單場預測 $N \ge 200$ 筆。在此之前，嚴禁任何中間調參。
