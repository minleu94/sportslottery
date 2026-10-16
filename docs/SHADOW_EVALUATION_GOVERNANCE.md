# Shadow Evaluation & Forward Performance Governance Protocol

**Protocol Version**: `v1.0-live`  
**Effective Date**: `2026-09-18`  
**System**: Taiwan Sports Lottery Decision System (`C:\Projects\PythonProjects\sportslottery`)

---

## 1. Strategy Versioning & Immutability Standard

1. **Active Base Version**: `strategy_version = v1.0-live`.
2. **Metadata Binding**: 所有預測快照（Prediction Snapshots）與串關候選單（Parlay Candidates）強制記錄：
   - `strategy_version`: 當前策略版本字串
   - `code_version`: Git Commit Hash 或原始碼簽章（SHA-256）
   - `model_versions`: 足球 Dixon-Coles 與棒球 Elo 模型精確版本
   - `evidence_weights_version`: 訊號權重設定版本
3. **版本分支原則**: 若未來進行任何模型抽換、門檻值調整或權重變更，一律升級為新版本（`v1.1`, `v1.2`），**嚴禁覆蓋或回溯竄改歷史版本的驗證記錄**。

---

## 2. Small Sample Safeguard & Anti-Overfitting Protocol

1. **極小樣本警告門檻 ($N < 30$)**:
   - 任何情報源（Crowd, Expert, Model）或分組階梯（HIGH, MED, LOW, Delta Buckets）在樣本數 $N < 30$ 時，系統與報表必須標示：
     $$\text{⚠️ INSUFFICIENT\_SAMPLE}$$
   - 此時嚴禁據以進行任何權重或門檻調整，亦不得於 UI 宣稱任何統計結論。
2. **調參審查門檻 ($N \ge 100$)**:
   - 唯有在特定賽事類型或情報源累積超過 100 筆已結算實盤預測後，才得啟動調參審查。

---

## 3. No Mid-Test Weight Changes (嚴禁測試期偷調權重)

在影子前瞻評估期間：
- **絕對禁止**因短期幾天連輸或結果不佳，私自修改：
  - `HIGH` / `MED` 共識門檻
  - 大神權重分配
  - 外部模型信心權重
- 所有評估必須完整歷經賽季波動，維持客觀記錄。

---

## 4. Source Kill Rule (無效來源熔斷規則)

若某外部情報來源（如特定大神、爬蟲源或模型 API）出現以下狀況：
- 連續超過 14 天無法取得數據（`UNAVAILABLE`）
- 數據過期率 $> 50\%$（`STALE`）
- API 格式破裂（`BROKEN`）

**處置規則**：
- 系統必須明確將其標記為 `DISABLED`。
- **嚴格禁止**偷偷退回造假假資料或隨機假資料填充。

---

## 5. Learning Rule (禁止自動線上學習迴圈)

- 系統**不做**線上自動微調（No Automatic Online Learning / Auto-Tuning）。
- 實盤結算僅作為「資料累積」與「人工作業審查」，杜絕預測系統產生自體反饋偏差（Feedback Loop Bias）。

---

## 6. Real Wallet Frozen (真實錢包絕對隔離)

- 每週 NT$200 預算錢包（Weekly Wallet）、獲利保留池（Prize Pool）、真實實盤注單記錄器（Ticket Recorder）**完全凍結（FROZEN）**。
- 影子投資組合（Shadow Portfolio）使用專屬 SQLite 資料庫與虛擬 NT$10 固定注金，**與真實錢包 100% 邏輯與實體隔離**。

---

## 7. First Milestone Target (第一審查里程碑)

累積達成以下任一條件前，維持純粹資料收集：
- **實盤前瞻驗證進行滿 30 天**，或
- **累積已結算單場預測筆數 $N \ge 200$ 筆**。

達成第一里程碑後，正式出具：
`FORWARD_VALIDATION_REPORT.md`

---

## 8. Core Forward Research Questions to Answer

審查報告必須以客觀實盤數據具體回答以下八大核心問題：
1. **Does HIGH outperform MED?** (HIGH 共識勝率與 ROI 是否真實高於 MED？)
2. **Does Expert improve Crowd?** (大神推介能否有效過濾或修正大眾盲從？)
3. **Do Models improve Market?** (外部機率模型是否能戰勝台彩開出的莊家盤口？)
4. **Which sports have enough evidence?** (哪些運動具備充足情報深度，哪些運動缺乏實質依據？)
5. **Which sources add no value?** (哪些情報源在長期實盤中淨貢獻為負或零？)
6. **Does higher model-market delta help?** (當模型勝率與台彩隱含勝率差距 $> +5\text{ pp}$ 時，實盤勝率是否更高？)
7. **Are 25-75x parlays better/worse than 10-25x?** (中倍率推進型串關在扣除本金方差後，期望值是否優於穩健防守型？)
8. **Does Closing Line Value hold?** (預測時賠率是否經常優於臨場關盤賠率？)

---

## 9. Product Reality & Non-Promotional Stance

- **產品真實定位**：台灣運彩前瞻決策輔助與研究工具（Decision Support & Research Platform）。
- **嚴禁誇大宣稱**：在缺乏數百至數千筆長期實證統計前，嚴禁在任何文件、UI 或宣傳中將系統描述為「穩贏/保證獲利」系統。
