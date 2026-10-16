# 玩運彩公開專家來源與抓取證據

本文件記錄 2026-10-12 的唯讀原頁檢查。完整 response body、取得時間、HTTP 狀態、URL 與 SHA256 保存在 [`tests/fixtures/playsport_public_sources_20261012/manifest.json`](../tests/fixtures/playsport_public_sources_20261012/manifest.json)。這些 HTML 是該次抓取的固定證據，不代表其內容仍是即時資料。

| 公開來源 | 此次原頁狀態 | 可以驗證的資料 | 系統處理 |
|---|---:|---|---|
| [主推榜](https://www.playsport.cc/billboard/mainPrediction?allianceid=1) | HTTP 200，73,608 bytes | 原始 HTML 含 `var vueData` JSON，兩種主推盤、排名、玩家 ID、歷史勝敗、勝率、樣本數與計算時間 | 做為公開候選名單；主推榜本身不代表該玩家推了本場 |
| [勝率榜](https://www.playsport.cc/billboard/winRate?allianceid=1) | HTTP 200，91,786 bytes | 原始 HTML 含 `var vueData` JSON；全盤、讓分、大小分類，含排名、勝率、勝敗與計算時間；頁面說明每日 14:00–17:00 計算戰績 | 做為同一平台的第二種候選名單與歷史績效，不算第二個獨立來源，不做本場機率 |
| [單場殺手榜](https://www.playsport.cc/killer/singleKillerRank?alliance=1) | HTTP 200，164,964 bytes | 公開排行頁可見評選勝率、獲利、期別與榜單玩家 | `RANKING_ONLY/PAID_PICK_UNAVAILABLE`；排行不能證明本場選項，購牌推薦未抓取、不推斷、不計支持 |
| [主推榜候選人 aoosoo1 的會員頁](https://www.playsport.cc/member/aoosoo1/prediction?allianceid=1) | HTTP 200，45,811 bytes | 有 `bank-tablecon`，此次沒有 `sellpredict-item`、明確日期或可解析推薦 | 此次頁面沒有可驗證推牌；解析器保留空結果與 UNKNOWN 日期，不補成今天 |

## 六位去重候選人的第二批會員頁檢查

這次從已保存的主推榜與勝率榜 HTML 抽取會員 ID，按會員 ID 去重後，最多再讀 6 個公開 MLB 候選頁。候選順序是主推榜第 2–7 名；aa5220 也出現在勝率榜，仍只抓一次、歸為同一 `PLAYSPORT_EXPERT` 群組。全部請求為無登入、無 cookie 的單次 GET。response body、SHA256、UTC 取得時間及 URL 保存在同目錄 `manifest.json`，以下解析使用 production adapter 的 `_parse_member_prediction_html` 同一實作。

| 榜單候選 | 本次會員頁 | HTTP／bytes | 舊版 parser 記錄的文字候選列數（非 verified pick） | 原始推牌（`pick_date`；發布精度） |
|---|---|---:|---:|---|
| GO108792，主推榜第 2 | [公開會員頁](https://www.playsport.cc/member/GO108792/prediction?allianceid=1) | 200／63,217 | 2 | `主 +1.5`（未知；UNKNOWN）；`主 -1.5 \| 6.5分`（未知；UNKNOWN） |
| aa5220，主推榜第 3、勝率榜候選 | [公開會員頁](https://www.playsport.cc/member/aa5220/prediction?allianceid=1) | 200／64,470 | 2 | `大7分贏50%`（未知；UNKNOWN）；`主讓 1分輸50% \| 大7分贏50%`（未知；UNKNOWN） |
| GO039157，主推榜第 4 | [公開會員頁](https://www.playsport.cc/member/GO039157/prediction?allianceid=1) | 200／49,853 | 0 | 沒有可由 parser 解析的公開推牌 |
| asd1986，主推榜第 5、勝率榜候選 | [公開會員頁](https://www.playsport.cc/member/asd1986/prediction?allianceid=1) | 200／61,015 | 0 | 沒有可由 parser 解析的公開推牌 |
| Futurestage870912，主推榜第 6 | [公開會員頁](https://www.playsport.cc/member/Futurestage870912/prediction?allianceid=1) | 200／46,130 | 0 | 沒有可由 parser 解析的公開推牌 |
| FangFang092130，主推榜第 7 | [公開會員頁](https://www.playsport.cc/member/FangFang092130/prediction?allianceid=1) | 200／64,197 | 0 | 沒有可由 parser 解析的公開推牌 |

第二批 6 頁當時由舊版 parser 記錄 4 列文字候選，來自 2 個會員頁；這不是 4 筆已驗證推牌或可支持本場的推薦。四列均沒有可確認的公開發文日期／時間，`pick_date` 為 `None`、`pick_timestamp` 為 `TIMESTAMP_UNKNOWN`、`publication_time_precision` 為 `UNKNOWN`。依 parser v2 同一原始 HTML 重讀後，aa5220 兩列都因國際盤標記排除；GO108792 的一列台灣格式讓分牌因日期及 event 身份缺失，仍無法配對本場，另一列因混合玩法排除。因此七位已檢查的去重會員目前有 **0 筆可驗證本場支持**。不拆多市場原文、不修補缺失發布時間，也不把榜單名氣或勝率當本場機率。

主推榜與勝率榜都是玩運彩同一平台，統一歸入 `PLAYSPORT_EXPERT`。它們只負責候選人發現與歷史績效，不能算作已驗證本場推薦；metadata 以 `board_role=candidate_discovery_only` 標記。七頁檢查中，有會員頁與榜單排名可讀，也有 4 列未核對公開推牌；目前仍是 0 筆已驗證本場支持。單場殺手榜也只有公開排行榜，付費牌面不會補足這個缺口。同一玩家只抓一次會員頁，同一實際牌按玩家、賽事隊伍、玩法、方向、盤線與公開日期去重。歷史榜單勝率只存在 `historical_win_rate` / `score`；該信號的 `probability` 為空。本場支持度由同場、同玩法、同盤線中支持與反對的可驗證推薦計算，欄位為 `support_ratio`。

公開會員頁未出現明確發文日期時，`pick_date` 與 `pick_timestamp` 保持未知；未知日期不能匹配賽前賽事。信號還要求榜單與會員頁的觀察時間都早於開賽，且必須是 timezone-aware datetime。只有日期而無時間的推薦若來源頁在開賽後才被觀察，不會成為賽前支持。若頁面有年月日，日期以頁面所示日期保留；賽事的 UTC 開賽時間先轉成台北日期再比較。榜單的 `process_time` 只是榜單計算時間，不能冒充推薦發文時間。

## Parser v2：原始列保留與可投票推牌分開

上表的四列是第一次檢查時由舊版 parser 對原始文字做的候選解讀，manifest 的原始 HTML、SHA256、HTTP 資料與當時紀錄均保留不變。依 parser v2 對同一份已保存 HTML 重讀後，這四列都不是已驗證支持：aa5220 的兩列使用 `betinfo_i` 國際盤標記，且帶有結算百分比；GO108792 的 `主 +1.5` 是一筆明確的台灣讓分列，但日期與 event ID 未知，所以目前仍不能配對本場。GO108792 的 `主 -1.5 | 6.5分` 是同列多市場文字，保留為歧義診斷。這是新增的 parser 解讀，沒有改寫原始頁或歷史 manifest 的舊 parser 結果。

Parser v2 只把明確位於 `bank-tablecon` 台灣容器，或玩法 cell 明確標記 `betinfo` 且沒有 `betinfo_i` 國際盤標籤的列，視為台灣來源候選。來源標籤不明、國際盤、結算結果（例如「贏／輸 50%」）、多市場分隔列、重複方向或玩法／盤線不完整的文字，只透過 `get_parse_diagnostics()` 保留原文、來源 URL、同次抓取的觀測時間與發布精度及拒絕原因；這些列不會構成 `VerifiedExpertPick`，不會投票。盤線依唯一玩法上下文解析，不能取任意第一個數字。有效玩法僅限明確單一的不讓分、帶正負號的讓分與大小列；不同盤種（尤其國際盤與台灣盤）不互相換算。

Parser v2 的回歸測試直接使用已保存的 `member_aa5220.html`、`member_GO108792.html` 與原有 `playsport_expert_asukajohn.html`，另以隔離 synthetic HTML 驗證完整日期時間、單一玩法盤線及歧義拒絕。Synthetic 頁只驗證 parser 契約，不是公開推薦證據。

原始來源 fetch 失敗、HTTP 403、解析不到榜單時，抓取結果帶 `HTTP_403`、`FETCH_ERROR` 或 `PARSE_EMPTY`；可用過期 cache 時標成 `STALE_CACHE` 並保留快取年齡，沒有快取時不回傳假 LIVE。HTML 快取解析結果有短 TTL，避免 `st.cache_resource` 長駐實例永久凍結玩家與推牌。

2026-10-12 這次原始榜單與會員頁請求均回 HTTP 200；因此沒有把既往的 403 描述成此次觀察結果。單場殺手榜雖可讀公開排行，其付費推薦內容不屬於可讀公開來源。網頁搜尋摘要或舊版快取只作為頁面路徑線索，本文件的狀態以 manifest 保存的原始 HTTP response 為準。
