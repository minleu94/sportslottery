# 瘋狗流修正與驗證紀錄

狀態：已授權的程式修正與驗證完成；模型準確度仍未通過台灣前瞻驗收。

## 要求與證據

| 要求 | 實作與驗證來源 |
| --- | --- |
| 大神混合牌面拒絕解析，未知日期不計支持 | integrations/experts/playsport_expert.py；tests/test_expert_source_upgrade.py |
| 同名策略依程式、設定、模型與協定分開 | core/experiment_identity.py、core/strategy_version.py、core/performance_metrics.py；tests/test_reproducibility.py |
| 多運動賽果配對與台灣盤口結算 | integrations/results、core/settlement_engine.py；tests/test_multisport_settlement.py；西甲官方原始 feed 見 laliga_sources/manifest.json |
| 時間切分模型與市場 Brier、Log loss、命中率、ROI | core/model_acceptance.py、core/research_reporting.py；歷史校準報告位於 ../model_acceptance_calibration_audit_20261013；台灣前瞻資格另外判定 |
| 主畫面先呈現資料完整、有效支持與打平門檻 | app.py、ui；tests/test_source_overview.py；實際 Streamlit 瀏覽器檢視 |
| 左側兩頁獨立圖示、完整名稱、清楚展開控制 | ui/navigation.py；tests/test_navigation.py；實際瀏覽器 DOM 與畫面檢視 |
| 盤口排除原因與搜尋範圍可判讀 | core/bet_validation.py、core/parlay_engine.py、app.py；tests/test_parlay_search_diagnostics.py |
| 獨立背景研究流程、實際排程與恢復 | core/research_pipeline.py、config/research_pipeline.yaml；tests/test_research_pipeline.py；實際 run.json 與 scheduled-task-last-run.json |
| 整張串關前瞻驗證及共用賽事風險 | core/parlay_validation.py；tests/test_parlay_forward_validation.py；parlay-current-audit.json |

## 解讀限制

- 過期、已開賽等原因可同時命中同一個選項；各原因相加不是排除總數。賠率範圍不會使過期或已開賽資料合格。
- 串關使用有限搜尋池。搜尋池沒有符合倍數的組合，不代表所有原始盤口不存在組合；畫面揭露池大小與限制。
- 已有 HTTP 成功但官方頁面明確顯示今日無比賽時，記為 LIVE_NO_EVENTS；沒有這個證據的空解析仍記為失敗。
- 未支援的足球聯賽保留明確未解決狀態，不套用其它聯賽模型、不猜測賽果。
- 歷史外部聯賽校準不是台灣運彩前瞻成績。模型需通過目前設定的獨立校準、時間切分與市場比較門檻，才可進入正式支持與排名。
- 測試通過只證明覆蓋的程式規則；目前有效已結算樣本數與資格以 ledger-audit.json 為準。
- 背景流程不建立或扣款實體及模擬錢包。排程使用目前使用者 Interactive 登入；電腦須開機且使用者登入。

## 最終驗證檔案

pytest-verification.json 記錄完整測試前後程式雜湊；pytest-final.txt 與 pytest-final.xml 記錄結果。
ledger-audit.json 記錄快照封存完整性、目前實驗有效樣本及訓練資料可用性。
scheduled-task-last-run.json 與 scheduled-task.xml 記錄實際 Windows 排程狀態。

最終完整 suite：329 passed、6 個需另行啟用的即時網路測試 skipped；測試前後及目前程式 hash 一致。另已直接用真實來源執行 runtime_final，全8步驟 SUCCEEDED、338選項、5個 LIVE來源與3個有明確無賽事證據的 LIVE_NO_EVENTS來源、17筆賽前快照。Windows實際排程已啟用、Ready、最後回傳0、PT15M，失敗run的第三次結算重試成功並完成報表。當前實驗有效已結算N=0；66筆中央ledger封存payload皆驗證通過。completion-checks.json保存跨檔核對結果。

## 歷史模型驗證的結論

2023–24 訓練、2024–25 選參數與校準、2025–26 鎖定評估的報告已完成。原融合模型在英超 holdout 的 Brier 0.633596、Log loss 1.054572，市場分別為 0.612056、1.019546；顯示原估計沒有優於市場。較早資料擬合的溫度校準改善英超融合估計，但西甲校準後仍劣於市場。這些結果支持維持模型研究狀態，並繼續蒐集台灣前瞻證據，不支持宣稱模型可靠或可穩定獲利。

## 介面與範圍

ui-review.json 記錄實際瀏覽器側欄40px展開／收合操作、完整圖示與頁名，以及338來源選項的組單說明。最終重新載入說明頁已確認研究英超1200筆截至2026-10-12、Elo25場截至2025-03-29，舊版1180筆資料獨立標為歷史參考。MLB Elo仍需由背景流程補齊官方歷史，尚未追上目前日期。西甲真實feed與中文模型fit回歸通過；其餘未支持足球聯賽明確留待未解決，不猜測。
