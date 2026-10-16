# 瘋狗流：五項後續改善

狀態：五項功能已完成，Luna 實作後由主代理檢查程式、全套測試、實際來源與介面。這份紀錄不宣稱模型已通過前瞻驗收。

## 交付範圍

| 要求 | 實作 | 驗證依據 |
| --- | --- | --- |
| 資料與排程健康頁 | 側欄「資料健康與研究工具」；來源最後成功／時效、流程失敗與恢復、原生Windows任務查詢、模型落後天數、按可用盤量排序的聯賽串接表 | tests/test_research_health.py、test_research_operations.py、test_research_tools_page.py；實際瀏覽器檢視 |
| 搜尋更完整 | 納入所有合格選項與賽事；精確賠率區間剪枝、可調搜尋節點預算、明確未完成狀態；保留每種風格最高排名12張 | tests/test_parlay_search_diagnostics.py：獨立暴力枚舉對照、超過16場、每場超過2個選項、預算耗盡及可證明的空結果 |
| 擴充結算 | 哥倫比亞、哥斯大黎加及目前最大可用缺口MLS；30隊、15場MLS來源對手與時間逐一核對；補齊實際NBA兩場缺隊名問題 | football_sources/manifest.json、test_colombia_costa_rica_settlement.py、test_mls_espn_integration.py、test_nba_run_settlement_identity.py；shared_settlement/verification.json |
| 價格／CLV追蹤 | 同場同玩法同選項同線、預測後且開賽前的最後真實觀測；列距開賽間隔、15分鐘內樣本與缺資料狀態 | core/clv_reporting.py、core/odds_watcher.py、tests/test_clv_and_recommendation_replay.py |
| 推薦重播與版本比較 | 單關及整張串關的封存版本、原始機率／價格／支持、逐腿快照及算術驗證；共同合法已結算選項才比較版本 | core/recommendation_replay.py、tests/test_clv_and_recommendation_replay.py、tests/test_parlay_forward_validation.py |

## 使用

從左側「資料健康與研究工具」開啟三個分頁：資料與排程健康、CLV價格追蹤、推薦重播與版本比較。
主畫面組單可調「搜尋運算預算（節點數）」並展開搜尋範圍。預算用完時顯示未完成；不能把空結果當作不存在組合。
價格追蹤由既有每15分鐘背景流程蒐集，不扣款。Windows任務需要目前使用者登入與電腦開機。

## 解讀限制

- CLV使用賽前最後觀測，不能證明那就是官方最後接受的封盤價格。
- 來源有賽果路由不代表所有隊名都已驗證：兩個中美／南美聯賽只加入實際核實的隊名；MLS涵蓋本次30隊。其它未核實聯賽仍明確保持未支援。
- 延期保持待定，未開始的賽事不結算；足球使用正規90分鐘規則。新規則也修正不平局時「和局」選項的誤判。
- 版本比較依完整身份與共同選項，樣本不足留空；歷史結果不合併進新版實驗。
- 重播只採封存雜湊涵蓋的欄位，較舊schema未涵蓋的附加欄位不能改變重播估計。
- MLB舊賽程的延期紀錄須以相同官方gamePk、主客隊、賽事類型及官方日期核對重賽明細；缺少 live 比分直接拒絕。原始賽程、核對欄位與來源雜湊保留，後到賽果由完整官方帳本重播。
- MLB共享研究資料仍在暖機補齊：本次已更新到2025-04-22，尚有延期日期待核對。流程完成不代表模型資料已追上今天。
- 全部合格選項都納入搜尋，但節點預算可能耗盡；此時明確顯示未完成，結果不能視為全域最高排名。實際背景四個倍率區間均保留此診斷。

## 驗證紀錄

驗證時間：2026-10-14 15:50 America/Los_Angeles（檔案時間皆標示UTC）。

- `pytest-final.txt`／`pytest-final.xml`：**364 passed、6 skipped**；6項為需明確啟用的網路測試。
- `pytest-verification.json`：測試前後程式hash一致，`2baf306f5fd57e8a74bb2c5338c07ec5ccc45cfbe050a9d9be949107bd37815d`。
- 前兩次全套的Windows檔案占用失敗保留於`pytest-first-attempt.*`、`pytest-second-attempt.*`。已補有限次原子替換重試；永久拒絕仍拋出、保留原檔，兩種情境均有測試。
- `runtime_final2/runs/20261014T2245Z/run.json`：最終版本真實完整流程COMPLETE、所有8個階段成功，8個來源觀測；47筆單關、96張串關封存重播。
- `completion-checks.json`：最終實驗身份一致、所有保存單關hash通過，96張串關hash與算術通過；共享帳本51筆已結算屬跨歷史版本的營運紀錄，不當作新版模型樣本。
- `shared_settlement/verification.json`：實際NBA兩場共36筆歷史快照透過正式結算流程配對完成；其餘未完賽資料保持待定。
- `scheduler-final.json`：研究Windows任務啟用、Ready、上次回傳0。每15分鐘持續執行；新程式身份將在下一個新時間窗口收集共享樣本。
- `ui-review.json`：實際瀏覽器確認三個側欄完整名稱與圖示、健康／CLV／重播三分頁、整張串關證據及共同样本不足提示；主畫面可調搜尋預算並顯示完成狀態。

當前新版模型的有效已結算樣本仍為**0**，不能判定模型勝率估計可靠或有獲利優勢。CLV也尚無距開賽15分鐘內的有效已完賽樣本。過往與新版本成績不混算。
