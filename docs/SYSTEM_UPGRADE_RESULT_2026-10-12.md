# 瘋狗流來源、顯示與系統修復結果

本輪來源核驗與修復已完成。使用固定三個 Luna 子代理並沿用原代理，主代理逐輪檢查來源、帳本、模型、搜尋、結算與顯示；沒有增加代理。修復後仍定位為賠率研究與本機注單記錄工具，模型準確度與正 EV 尚未經實證證明。

## 先看懂數字

EV = 估計命中率 × 十進位賠率 − 1。例如賠率 2.0、假設命中率 60%，EV 是 +20%；每次 20 元的平均淨損益試算是 +4 元。真正命中率若只有 40%，同一賠率的 EV 就變成 −20%。這是假設下的長期平均，沒有保證單次結果。

| 畫面數字 | 意義 |
|---|---|
| 打平門檻 | 1 ÷ 賠率；2 倍需 50%，100 倍需 1%，都是打平所需比例 |
| 模型估計命中率 | 未校準模型的判斷；缺有效模型時只顯示市場基準 |
| 大神歷史勝率 | 網站榜單的歷史表現，不能直接當成本場機率 |
| 社群支持率 | 選擇該選項的人數比例 |
| HIGH／MED／LOW | 情報支持程度，沒有固定勝率對應 |
| Edge／Delta | 模型機率與打平門檻的差，單位為百分點 |
| ROI／CLV | 已結算報酬／與相同玩法盤線最後賽前觀測價的比較 |

主頁已連到「指標與資料來源」頁，提供 EV／注金互動試算、賠率對照、玩法解釋與來源說明。原頁連結、抓取時間、發布精度與缺資料原因可逐關核對。

## 真實來源核驗

此次保存 10 個原始 HTTP response：主推榜、勝率榜、單場殺手公開排行，以及 7 個去重的會員頁，均回 HTTP 200。每個 body 的 bytes、SHA256、URL 與 UTC 時間已核对。

7 個會員頁共解析出 4 列公開牌，來自 2 頁。四列都缺少可確認的發布日期／時刻，也沒有核對到本次合法賽事，因此 **本次可驗證本場支持仍為 0**。其中有混合讓分與大小文字的解析歧義，原文保留；不得當作新增有效推薦。其餘頁面沒有可解析公開牌。

主推榜與勝率榜只擴大候選發現，仍屬同一玩運彩群組；同一會員跨榜去重。單場殺手的公開牌排行與付費推薦分開，付費內容未取得。玩運彩盤口是第三方記錄，並未逐筆核對官方實際接受價格。

詳細原頁與內容見 [來源證據](EXPERT_SOURCE_EVIDENCE.md)，原始檔與 manifest 在 [固定 HTTP 證據](../tests/fixtures/playsport_public_sources_20261012/manifest.json)。這些 response 是該次觀察的證據，不代表現在仍即時。

## 已修復並核對的範圍

| 項目 | 結果與驗證 |
|---|---|
| 來源與快取 | LIVE／CACHED／STALE_CACHE／403／空頁／UNKNOWN 有文字狀態；缺時間不補現在，投票缺失不補 50% 或 0 票。強制刷新會更新盤口、會員頁與模型 state。 |
| 事件身份 | 未知開賽時間不捏造；UTC／台北日期、跨年、provider ID 復用與同隊雙重賽有回歸。 |
| 帳本 | 注單與扣款在同一 SQLite 交易內；派彩原子保存、有限金額、每週 200 上限並發檢查、舊 schema、失敗回滾、重試只扣一次、同 key 不同內容拒絕。 |
| UI 記錄 | 搜尋、畫面、記錄共用資料核對；低於 10 元餘額不造成 widget 錯誤。只記錄已購買注單，人工補記另標示；快照失敗會顯示並可無重複扣款重試。 |
| 搜尋 | strict 要每關至少 2 個有效來源群組；無靜默放寬，未 ready 盤口不擠掉合法候選，LOW 不進高共識。每分類只保留 top 12，與小樣本完整排序核對。候選池仍限 16 場、每場 2 個選項。 |
| 機率／EV | 完整二向或足球三向市場才去水；歷史榜單勝率與人氣不改本場概率。模型按資料群組去重，配置 weight 真正生效，0 weight 不投票。移除假樣本數／假 90% 區間；CI、保守 EV 未知。 |
| MLB 模型 | neutral 1500 起始；官方 Final 更新 CLI、gamePk 去重、原始比分驗證、時間順序、原子 state 保存。拒絕損坏 state 覆寫及亂序增量；同日完賽時刻未知時不供早場預測。未使用投手／休息日調整。 |
| 足球與 fallback | Dixon 按 league／cutoff／內容 hash 共用最多 8 組 LRU fit；未知日期／非法比分取消已驗證標記，未支援讓分不造概率。ESPN 快取有 TTL、觀測與賽季；時效不足、賽季不符或賽後 snapshot 只供參考。 |
| 結算／CLV | WON／LOST／VOID／PUSH／PENDING／UNRESOLVED 保真；完整隊伍與 UTC 時間或 source ID 唯一配對，不靠單隊 substring。歷史事件日期抓取，缺比分不補 0。最後賽前價格按相同身份與盤線核對，未知則無 CLV。 |
| 前瞻研究 | 明確模型融合與 data_as_of；缺／過期／賽後資料排除。快照 schema 3 hash 覆蓋資格、機率、來源、設定與身份，保留舊 hash 契約；鎖定寫入、原子更名與故障回報。統計只收目前策略合格已結算 binary 樣本，市場基準不算模型校準。 |
| 影子資料 | canonical event／開始時間與盤線指紋、並發提交去重、已結算不重寫；主頁與週報排除其它策略／未合格影子注單。影子流程不扣真實錢包。 |
| 可重現 | `v2.0-research`，74 個 runtime／設定／依賴文件內容 hash；鎖定 98 個直接與間接套件。CLI help、離線測試、文件與瀏覽器預覽核對。 |

完整 content hash：`e5f80b3c88b01f655b6bb87fa5961dac2bdfdbd645e228496abb6c634e8a5cae`。保存的版本／設定清單見 [策略 metadata](../artifacts/upgrade_strategy_metadata_20261012.json)。往後更動權重或策略行為應另立版本，保留原始快照供審查。

## 驗證與使用

最終離線測試 **191 passed，6 live tests 依設定略過**；Python 編譯檢查通過。測試包含隔離來源→訊號→搜尋→帳本→快照→賽前價格→結算→指標流程。所有测试帳本、模型 state 與報告使用隔離資料，沒有用測試改寫正式注單。

Windows Codex `AC/Temp` 在部分 run 限制 `os.replace`，完整驗證改用專案內新建、已確認路徑的隔離 basetemp；沒有跳過原子保存測試，也沒有降低為非原子寫入。結果與指令在 [最終 pytest log](../artifacts/upgrade_pytest_20261012_final.txt)。這輪沒有執行整套 live integration，也沒有更新正式 MLB state 或替使用者投注。

```powershell
python main.py
python main.py update-mlb-elo --help
python main.py snapshot --help
python main.py settle --help
python main.py weekly-report --help
python main.py watch-odds --help
python main.py export-research --help
```

執行真正 MLB 更新後，按主頁「刷新盤口與模型資料」載入新 state。週報為目前策略累積結果，週別為產出標籤。正 EV、HIGH 或達到 30 筆仍不足以證明獲利；缺少合格資料時維持空結果是目前的正確行為。

說明頁瀏覽器預覽：[截圖](../artifacts/metric_guide_upgrade_preview.jpg)。
