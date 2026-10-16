# 瘋狗流程式不足評估

評估日期：2026-10-14，America/Los_Angeles。主代理與兩位 Luna 以目前程式、設定及已保存的實際資料做唯讀審查；本次未新增或執行測試。既有364項通過的測試紀錄是上次交付證據，不代表本次沒有發現新缺陷。

## 判斷

目前已具備有來源紀錄、身份隔離、前瞻封存、結算與驗收門檻的研究系統。但資料推進仍有缺陷，模型在目前產品價格與資料範圍上的優勢仍未成立，部分寫入與維運流程也缺少一致的成功保證。尚不足以將其視為已驗證的勝率或獲利推薦系統。

`evidence.json`保存本次讀到的實際run、結算稽核、週報、程式hash與觀測時間。背景流程持續執行，因此以下數字均為此次觀測的截面；不是永久總數。

## 1. P0：MLB待定日期未可靠清除（已觀察的狀態矛盾）

參考共享run於研究帳本的UTC2026-10-15 00:07完成，即使用者當地2026-10-14 17:07。Elo停在2025-04-22，已查詢到2025-05-31，526場完賽資料被保留等待，12個pending日期卻沒有pending_game_ids。背景流程繼續擴充帳本後，主代理再核對這12天的159場比賽，全部為Final；逐日gamePk與來源hash保存於`mlb-pending-audit.json`。數量增加不改變待定日期沒有未完賽賽事的矛盾。

程式先把live feed核對結果寫進`fetched`及帳本，但之後以未更新的`fetched_by_date`原始賽程重新判斷pending；只有部分移動日期的情境會清除。舊延期stub或空回傳可讓已完成日期持續阻擋水位。

來源：[pending計算](C:/Projects/PythonProjects/sportslottery/core/research_pipeline.py:1115)、[阻擋完賽套用](C:/Projects/PythonProjects/sportslottery/core/research_pipeline.py:1144)。

下一步：以gamePk核對後的有效帳本與未解決賽事集合重新計算日期；保留來源完整性要求。驗收要包含同日live完賽、改期、空賽程、同日另有未完賽及連續多次更新。不能直接刪掉pending或跳過比分核對。

## 2. P1：目前並未收集到可評分的模型預測（已觀察）

當前身份279筆快照全部是MARKET_BASELINE_ONLY；模型候選機率數也是0，有效已結算模型樣本0。51筆歷史結算是其它身份的市場基準資料。等資料自然結算，不會把這些市場基準變成模型預測。

MLS、NBA等目前有可用盤量，卻沒有配置相應模型；MLB則因資料陳舊不能提供合格估計。應先讓至少一個有足夠實際盤口的聯賽形成「近期資料→賽前模型候選→真實結果→同身份評分」完整路徑。驗收門檻與最低樣本數應保留，不以放寬門檻製造模型通過。

來源：[models設定](C:/Projects/PythonProjects/sportslottery/config/models.yaml:1)、[未通過模型保留為候選、正式估計只採已驗收模型](C:/Projects/PythonProjects/sportslottery/core/signal_hub.py:279)、本目錄`evidence.json`。

## 3. P1：歷史驗證未建立市場優勢（證據限制）

已保存的英超holdout372場，raw Dixon–Coles Brier0.615492、Log loss1.027024；市場0.612056、1.019546，這兩個分數越低越好。配對區間跨零，不能宣稱raw模型確定優於或劣於市場。固定融合beta=0.65的英超Brier0.633596，並沒有因融合而改善。

這些歷史資料使用Football-Data/B365價格，覆蓋英超與西甲，不能代表台灣運彩或其它運動的收益。擴充模型特徵、融合權重或新聯賽時，應事先定義新評估，再使用新的保留資料；不重複調整已看過的holdout來宣称通過。

來源：[歷史報告及配對區間](C:/Projects/PythonProjects/sportslottery/artifacts/model_validation_review_20261013_luna/eng_1/report.md:43)、[歷史驗證範圍](C:/Projects/PythonProjects/sportslottery/core/model_validation.py:41)。

## 4. P1：有賽果資料仍存在配對缺口（已觀察；根因尚待逐場查）

參考run中，NBA取得26筆賽果紀錄，但156筆快照無唯一配對；哥倫比亞15筆、哥斯大黎加20筆也是NO_UNIQUE_RESULT_MATCH。這些是快照數，不是同數量的独立比賽。MLB與MLS另有RESULT_PENDING，應與配對失敗分開。

不能只靠「provider已接通」判斷可完整結算。應逐場列出來源ID、主客隊canonical ID、原開賽時間、provider時間及差異；延期須用可靠身份追查官方改期。不要以放寬時間或模糊隊名配對換取結算數。

來源：`evidence.json`的settlement_audit；[正式配對](C:/Projects/PythonProjects/sportslottery/core/settlement_engine.py:98)。

另外，亞冠二級、沙烏地聯賽、南美自由者盃等仍有未支援來源或模型的範圍。應按實際可用盤量維護來源、隊名、玩法與完整賽果的覆蓋表，不能宣称全足球覆蓋。

## 5. P1：資料写入的成功與復原保證不一致（程式可確認的失敗處理缺口）

盤口歷史寫入失敗只記warning，函式仍回傳record；batch仍增加count，因此背景階段可能報告成功取得觀測，但檔案沒有保存。串關封存寫入也有同類warning後繼續的路徑。串關結算直接write_text重寫整個帳本，未采用單關帳本同樣的檔鎖及原子替換。

這次未觀察到實際帳本遺失；不足是程式對寫入失敗、被終止及並行寫入的保證較弱。应統一有限重試、持久化後確認、跨程序鎖及原子替換；永久失敗要讓階段失敗，不能只留下log。備份與還原也應有可執行的驗收紀錄。

來源：[盤口寫入](C:/Projects/PythonProjects/sportslottery/core/odds_watcher.py:75)、[batch計數](C:/Projects/PythonProjects/sportslottery/core/odds_watcher.py:105)、[串關寫入](C:/Projects/PythonProjects/sportslottery/core/shadow_parlay_logger.py:198)、[串關帳本重寫](C:/Projects/PythonProjects/sportslottery/core/shadow_parlay_logger.py:318)。

## 6. P1：串關相關性與來源獨立性仍未經實證校準（方法限制）

相關守門已存在，不是完全沒有檢查。但同隊、全主／全客、時段及大小分等風險使用固定折減，最高25%，joint仍是各關機率相乘再折減。兩個來源被配置成不同群組，也不能證明其預測誤差獨立。

目前沒有足夠實際串關結果證明折減幅度合理。應保留「啟發式估計」標示，按聯賽／玩法及重疊事件評估誤差相關性、聯合命中與區間；模型未驗收前不把串關EV當成可信收益預測。

來源：[固定折減](C:/Projects/PythonProjects/sportslottery/core/correlation_guard.py:115)、[聯合機率公式](C:/Projects/PythonProjects/sportslottery/core/correlation_guard.py:194)、[來源群組](C:/Projects/PythonProjects/sportslottery/core/probability_evidence.py:66)。

## 7. P2：CLV觀測數與獨立樣本數混在一起（已觀察的統計表達限制）

本次近開賽15分鐘內100筆有效觀測，對應69個選項、13場比賽；重複觀測同一選項會被aggregate各算一次。有用於比較不同推薦時點的紀錄價值，但不應當作100場独立樣本。

應同時列「觀測數、唯一選項數、唯一賽事數」，預先定義首次推薦／固定提前時間等評估口徑，再按賽事計算區間。既有價格標示已诚實說明不是官方封盤價；仍需可靠封盤來源或更密集、有記錄的賽前輪詢才能改善此限制。

來源：[逐快照CLV](C:/Projects/PythonProjects/sportslottery/core/clv_reporting.py:78)、[按列数聚合](C:/Projects/PythonProjects/sportslottery/core/clv_reporting.py:143)。

## 8. P2：介面仍有容易誤讀的狀態（已確認）

- N=0時部分勝率／ROI仍以0%顯示；應統一成「尚無有效樣本」，與真實零收益區別。
- COMPLETE只表示工作流程完成；未配對、資料過舊及尚無模型樣本仍可能同时存在。應另列資料完整度、結算覆蓋率與模型可用狀態。
- 排除原因已正确說明可重疊，但仍只有彙總表，不能從「過期193」直接打開193個選項與時間／門檻。
- 賽季雷達ESPN排程讀取的失敗、未支援、無賽事都可回傳空清單；UI不能可靠區分這些情況。

來源：[空樣本ROI](C:/Projects/PythonProjects/sportslottery/core/performance_metrics.py:163)、[0%展示](C:/Projects/PythonProjects/sportslottery/app.py:1056)、[原因彙總](C:/Projects/PythonProjects/sportslottery/app.py:508)、[排程空回傳](C:/Projects/PythonProjects/sportslottery/integrations/schedules/espn_schedule.py:40)。

## 9. P2：搜尋結果仍不是全域最優保證（功能限制）

已修掉只取每場兩個選項與16場的靜默截斷，並加入未完成診斷。但預算耗盡只保存已訪問範圍的前12張，輸入／搜尋順序會影響可見結果。排序優先證據分数，其次估計EV，也不是最大化實際收益的已驗證目標。背景4個倍率區間分别取預算，沒有跨區間總耗時／公平進度規劃。

應補訪問覆蓋率、可恢復搜尋或跨事件公平分配，以及明確定義排名目標。大資料可採top-k bounds／剪枝优化，但必须另證明不漏更高排名候選。

來源：[事件訪問順序](C:/Projects/PythonProjects/sportslottery/core/parlay_engine.py:212)、[排名與前12張](C:/Projects/PythonProjects/sportslottery/core/parlay_engine.py:254)、[逐區間預算](C:/Projects/PythonProjects/sportslottery/core/research_pipeline.py:647)。

## 10. P2/P3：維運與部署仍偏向單一開發電腦（配置限制）

排程使用Interactive登入，需要使用者登入及電腦可執行；健康頁提供被動觀測，未見完整的異常推送與恢復通知。應先定义抓取失敗、模型水位停滯、結算积壓、磁碟／寫入失敗的可操作警報。

套件設定py-modules為空，package只包括core/integrations/probability/ui；可用入口main.py、Streamlit pages及config资源沒有一同納入，沒有保證搬到另一台機器／安裝wheel後可直接運作。launcher也有本機固定路徑。應建立乾淨環境部署／升級／還原流程。app與pipeline檔案較大，來源配置分散，也應逐步抽出資料契約與服務邊界。

來源：[Interactive任務](C:/Projects/PythonProjects/sportslottery/scripts/install_research_task.ps1:76)、[套件內容](C:/Projects/PythonProjects/sportslottery/pyproject.toml:23)、[固定路徑fallback](C:/Projects/PythonProjects/sportslottery/launcher.py:72)。這些部署問題本次由設定檢查確認，未進行新機器安裝測試。

## 建議處理順序與驗收

1. **MLB日期清除與結果配對**：以真實問題gamePk／賽事逐筆確認，連續背景更新能前進；未識別資料继续待定。
2. **統一寫入及失敗回報**：模擬占用、磁碟失敗、程序中斷與並行寫入後，資料不丟且成功計數與帳本一致。
3. **至少一個聯賽形成可驗證模型路徑**：相同實驗身份的賽前raw候選、來源水位、真實結果都齊全；按預先設定的時間分割與市場比較驗收。
4. **修正統計與UI口徑**：N=0留空，CLV同时显示觀測／選項／賽事數，排除原因可逐筆追查，流程成功與資料完整分開。
5. **補相關性與排名證據，再擴大聯賽**：先验证聯合估計与排序有意義；擴充完整資料鏈，而不只新增league代碼。
6. **告警、備份還原與可重現部署**：使系統離開当前開發機仍可按同樣設定運行与恢复。

最重要的驗收不是多通過幾項規則測試，而是實際資料能持續前進、來源與結果能一致配對，以及同版本模型在未參與調整的資料上有足夠證據支持其估計。
