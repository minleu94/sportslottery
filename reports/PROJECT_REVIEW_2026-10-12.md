# 瘋狗流專案改進審查

審查日期：2026-10-12（使用者時區）。以目前程式碼為準，舊完成報告不作為功能完成的證據。

## 判斷與建議順序

目前適合定位為「有每週預算控制的串關情報研究與注單記錄工具」。盤口、情報、模型、搜尋、實際帳本與影子帳本已經分開，這個結構可以沿用。下一步先修正帳本與結算的正確性，再建立可信的前瞻績效，最後才調整模型與搜尋體驗。

本次沒有修改產品程式、正式錢包或歷史預測資料。新增本報告、隔離重現腳本及程式結構圖譜。

## 1. 優先修正：扣款、注單與派彩必須是同一筆交易

證據：[ticket_recorder.py:99](../core/ticket_recorder.py#L99)、[ticket_recorder.py:215](../core/ticket_recorder.py#L215)、[wallet.py:stake_bet](../core/wallet.py)。

`place_ticket()` 先呼叫錢包扣款並提交，再另外建立注單。`settle_ticket()` 先入獲利池，再另外更新注單狀態。錢包方法也在交易外先讀餘額，再寫回計算結果。

隔離重現結果：

- 錢包 200 元，建立 20 元注單時注單 INSERT 失敗：錢包剩 180 元，沒有任何注單。
- 20 元、2 倍的贏單，派彩後注單 UPDATE 失敗；重試一次：獲利池入帳 80 元，原本應為 40 元，注單仍為 OPEN。
- 兩個請求同時各扣 150 元：都成功，流水實際記錄 300 元，錢包狀態卻只記本週下注 150 元。

修法：以同一 SQLite connection 和 `BEGIN IMMEDIATE` 包住讀取、額度驗證、扣款／派彩、注單及流水。結算 UPDATE 加上 `status='OPEN'` 並檢查更新筆數，對扣款／派彩加入唯一業務鍵。雙擊、兩個瀏覽器視窗、資料庫寫入失敗都要納入回歸測試。關閉 connection 要使用明確的 `close()` 或 `contextlib.closing`；SQLite 的 connection context manager 本身只管理提交／回滾。

## 2. 優先修正：影子結算可能把輸單算成贏單

證據：[settle_results.py:88](../scripts/settle_results.py#L88)、[settlement_engine.py:124](../core/settlement_engine.py#L124)、[snapshot_logger.py:297](../core/snapshot_logger.py#L297)、[settlement_engine.py:197](../core/settlement_engine.py#L197)。

正式腳本只傳 `actual_outcome`。但結算方法的 `settlement_status` 預設是 WON，因此 `actual_outcome=False` 仍會保存為 WON。後續串關優先讀這個狀態，可能將輸掉的關卡計為贏，污染模擬派彩和 ROI。隔離案例已重現這組矛盾欄位。

另一個問題是賽事配對：API 產生英文 `away@home` 字串，腳本拿預測中的隊名搜尋，且任一隊符合就選取。中文隊名通常無法匹配；若隊名可匹配，也沒有同時驗證兩隊、歷史開賽日期及雙重賽。同時，腳本掃描所有未結算預測，卻只抓單一目標日期的賽果。

修法：保留完整 `WON/LOST/VOID/PUSH/PENDING/UNRESOLVED` 狀態，禁止先轉成 bool 再猜回狀態；使用 canonical event ID、來源 game ID、兩隊與 UTC 開賽時間配對。依歷史事件日期批次取得結果，不能只查執行當天。棒球雨停與局數等狀態也要從來源一路傳到規則引擎。

## 3. 優先修正：過期盤口與已開賽事件的限制只有部分生效

證據：[parlay_engine.py:193](../core/parlay_engine.py#L193)、[app.py:589](../app.py#L589)、[ticket_recorder.py:83](../core/ticket_recorder.py#L83)。

搜尋會替過期組合顯示 ODDS_STALE，但確認下注按鈕沒有按 `is_ready` 停用，記錄注單的核心方法也不驗證盤口時效。隔離案例確實能將 STALE_CACHE 關卡記入注單。

此外，READY 只依盤口狀態判定，沒有檢查事件是否已開賽。兩個 2020 年事件，只要盤口狀態填 LIVE，仍會回傳 READY。

修法：在提交注單時統一驗證最新盤口時間、事件開賽時間與關卡資格；UI 同步停用按鈕並提供原因。保留人工補記歷史注單時，另設明確的補記流程，不能混入即時推薦或前瞻驗證。這裡的下注是本機記錄，並非已串接官方投注服務。

## 4. 優先修正：嚴格模式與「共識較高」會靜默放寬

證據：[parlay_engine.py:123](../core/parlay_engine.py#L123)、[parlay_engine.py:264](../core/parlay_engine.py#L264)。

strict 原本只保留 HIGH/MED，但合格場數不足時會退回全部 `valid_legs`。如果 high_consensus 為空，又會將平均評分至少 LOW 的 aggressive 組合補進 high_consensus。

隔離重現：只提供 LOW、LOW 兩關，選 strict，仍取得一張「共識較高」組合。

修法：保留使用者選擇的篩選條件；沒有合格組合就顯示合格場數與不足原因。使用者主動改成 wild 後才放寬。分類名稱和實際關卡最低品質必須一致。

## 5. 優先修正：Live MLB Elo 的名稱與資料品質不符

證據：[live_mlb_elo.py:40](../integrations/models/external/live_mlb_elo.py#L40)、[live_mlb_elo.py:134](../integrations/models/external/live_mlb_elo.py#L134)、[live_mlb_elo.py:218](../integrations/models/external/live_mlb_elo.py#L218)、[models.yaml](../config/models.yaml)。

目前模型預設載入手寫的球隊 Elo 常數；本機沒有 `data/live_mlb_elo_state.json`。搜尋全專案後，`update_game_result()` 的呼叫只存在測試，沒有正式更新工作呼叫它。`evaluate_leg()` 沒有將先發投手或休息日調整值傳入 `predict_match()`。

即使完全沒有歷史狀態檔，模型依然輸出 `freshness_status=LIVE`、`MODEL_HIGH_QUALITY`，`data_as_of` 則為空。隔離案例已重現。

修法：先將初始評分輸出標為 EXPERIMENTAL／未完成初始化。建立真實賽果回放、按 game ID 去重、按時間順序更新、定期保存與失敗恢復，再依最近成功更新時間判斷時效。只有真的代入投手資料時才展示投手調整已生效。

## 6. 模型與 EV：目前是啟發式估計，需要實證校準

證據：[edge_engine.py:129](../core/edge_engine.py#L129)、[edge_engine.py:146](../core/edge_engine.py#L146)、[edge_engine.py:214](../core/edge_engine.py#L214)、[correlation_guard.py](../core/correlation_guard.py)。

實際主流程沒有傳對向賠率，公平機率使用固定 8% 抽水估計；足球三向市場也未將主／和／客完整去水。模型融合權重、logit 收縮和相關性折扣多為手設係數。

所謂 90% 區間的有效樣本量，從 20 起算，每個模型訊號加 30、大神加 25、大眾加 15；不是來自預測誤差的實測樣本。隔離案例中，把同一模型訊號複製一次，就能讓區間縮小，儘管沒有新增任何資訊。

修法：先把畫面數字稱為「模型估計」，清楚顯示未校準狀態；使用完整市場賠率去水。按來源群組去重融合，採按時間切分的訓練／驗證／測試，評估 Brier、log loss、校準曲線及相對市場基準。完成校準後再決定是否使用 estimated EV 排名；相關性折扣在未經估計前應視為規則懲罰，不能作為已驗證的聯合機率模型。

## 7. 前瞻驗證：補齊結算與資料缺失的排除規則

本機歷史資料：981 筆預測快照，只有 1 筆已結算；影子帳本 3 張注單全部 OPEN。現有資料無法支持「HIGH 比 LOW 更準」或「高倍策略有正期望值」。

證據：[snapshot_logger.py:73](../core/snapshot_logger.py#L73)。缺少事件開賽時間，或日期格式解析失敗，`check_cutoff_integrity()` 都會回傳合格。隔離案例使用 `AM 06:40` 當開賽時間也通過。UI 補建快照時沒有保留 `start_time_utc`，可能進入這條分支。

修法：時間未知或格式錯誤時標示 `TIME_UNKNOWN`，排除嚴格前瞻指標；資料保存可以繼續。先把 snapshot → closing odds → result → settlement → weekly report 排成可重試的每日流程，持續累積已結算資料，再評估模型與串關策略。

## 8. 第二階段：提升速度、配置與可重現性

- `app.py` 每次 Streamlit rerun 都重新評估候選與搜尋；Dixon-Coles 每個關卡重新 `fit()`。相同聯賽、預測日期及資料版本可以共享 fitted model 和比賽預測。
- 搜尋會建立每張候選的大型 dict（包括全部序列化關卡），最後才各取 12 張。16 場、每場 2 個選項、2～6 關，最多需遍歷 686,368 組選項，實際接受數量再受賠率範圍限制。可用賠率上下界提前剪枝、每分類維護有界 top-k，再序列化最終結果。
- `evidence_weights.yaml` 雖被讀取，後續評分沒有使用其規則；模型 YAML 的 weight 也没有傳入 EdgeEngine。應建立唯一有效的配置路徑，並讓畫面顯示真正生效的配置。
- `app.py` 上方綠燈及模型覆蓋矩陣含固定文字，不是實際健康檢查結果。改為最近成功抓取、資料日期、失敗原因與模型載入狀態。
- 本目錄不是 Git repository，也沒有依賴清單。加入 Git、`.gitignore`、`pyproject.toml` 與鎖定依賴，分開離線單元測試和連網整合測試。`tests/test_run.py` 在匯入時就抓即時盤口，應移為手動診斷腳本。
- 策略 hash 只涵蓋少數舊檔案，漏掉目前啟用的 Live MLB Elo、EdgeEngine、CorrelationGuard 及模型配置；策略 metadata 的模型版本與結算版本也落後於目前程式。要涵蓋實際生效的完整策略與資料版本。

## 驗證範圍

已執行並通過 37 項既有測試：

```text
tests/test_engine.py + tests/test_quant_upgrade.py: 15 passed
tests/acceptance/test_shadow_research_integrity.py: 12 passed
tests/acceptance/test_shadow_evaluation.py: 7 passed, 1 deselected
tests/test_v3_system.py: 3 passed, 3 deselected
```

僅選擇隔離帳本、數學／規則及快照的測試；未執行會改写正式報告的測試或整套連網流程。現有測試通過不代表上述情境已覆蓋。

另外，[隔離重現腳本](../artifacts/review_20261012_checks.py) 成功重現 10 組問題／缺口。它的 assert 確認目前缺陷，並非修正後應維持的行為，修正後應改寫為真正的回歸測試。

程式結構圖譜只涵蓋目前 82 個 Python 檔案，755 個節點、1,677 個關係，未對歷史快照及舊報告做語意抽取。全量盤點有 860 個支援檔案、約 219 萬字，其中 data 750 個、core 28 個、tests 21 個、integrations 19 個、根目錄 13 個；全量建圖成本偏高，本次聚焦現行程式。1 個敏感檔案已略過。

圖譜完整性警告：原始 AST 關係含 292 個缺失端點關係，建圖合併了 83 個同端點關係，因此圖譜僅供導航，不能用它斷言所有呼叫已完整納入；以上問題均另以原始碼與隔離重現核對。圖譜語意抽取 token 成本為 0，並不代表本次人工審查的對話成本為 0。
