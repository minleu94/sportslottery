# Source Capability Matrix (國際市場情報來源能力矩陣)

> **Sportslottery — Phase 4：Global Market Intelligence & Prediction Quality Upgrade**  
> 最後審計更新：2026-10-31  
> 規範目的：明確記錄系統支援與候選之國際市場情報來源能力、授權條款、呼叫額度限制、資料時間戳與失效降級策略。

---

## 1. 核心來源能力總覽

| 來源識別碼 (`source_id`) | 來源分類 | 覆蓋運動 / 聯盟 | 支援玩法 (Markets) | 更新頻率 | 免費 / 配額限制 | API Key | 原始時間戳支援 | 歷史回測可行性 | 可靠度評級 | 降級策略 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `the_odds_api` | 國際博彩市場賠率 | MLB, NBA, NFL, EPL, LaLiga, UCL, J-League | 不讓分 (H2H), 讓分 (Spreads), 大小分 (Totals) | 5~15 分鐘 (可設定 Polling) | 免費方案 500 requests / 月；自適應快取保護 | 可選 (`ODDS_API_KEY`) | 完整 ISO-8601 UTC (`last_update`) | 是 (付費方案完整，免費僅快取) | HIGH | 當無 Key 或超額時，退回本機合約規格之合成測試 Fixture (`is_synthetic=True`) |
| `sharp_benchmark_pinnacle` | Sharp 尖銳市場基準 | MLB, NBA, NFL, 足球各大聯賽 | 獨贏, 讓分, 大小 | 賽前 10 分鐘 ~ 1 小時 | 免費本地計算 / 開源鏡像 | 無須 Key | 支援快照觀察時間 (`observed_at_utc`) | 支援點位回測 | HIGH (低水差 1.5%~2.5%) | 當單邊缺少時，拒絕進入 EV 評估 (`UNMATCHED`) |
| `action_network_splits` | 國際投注傾向 (Splits) | MLB, NBA, NFL, NCAAF, NCAAB | 讓分, 大小分, 獨贏 | 15~30 分鐘 | 公開 Web 彙總 / 頻率限制 1 次/分 | 否 | 支援觀測時間 (`observed_at_utc`) | 有限 (即時快照存儲) | MEDIUM | 缺失時保留 `bet_percentage=null, money_percentage=null`，不偽造比例 |
| `vsin_splits` | 國際投注籌碼分佈 | MLB, NBA, NFL | 讓分, 獨贏, 大小 | 30 分鐘 | 公開摘要報導 / 額度限制 | 否 | 支援發布時間 | 有限 | MEDIUM | 僅做參考資訊，標註 `reporting_scope`，不可直接推導為獲勝機率 |
| `espn_stats_api` | 獨立官方賽事數據 | MLB, NBA, NFL, 足球各大聯賽 | 賽程、即時比分、戰績、先發陣容、球員數據 | 即時 ~ 每小時 | 公開開放介面 (遵守 Rate Limit: 1 req/sec) | 否 | 完整比賽時間與排程 | 完整歷史季賽數據 | HIGH | 連線逾時則以 SQLite 本地季賽特徵快取替代 |
| `playsport_taiwan_odds` | 台灣運彩在地盤口 | 台灣運彩開盤之全賽事 | 讓分, 不讓分, 大小, 勝分差, 單雙 | 5~15 分鐘 | 本地 Scraper 快取 | 否 | 支援台灣時間與抓取時間 | 支援已落庫賽事 | HIGH (在地法定基準) | 當盤口關閉時標註 `odds_status=UNAVAILABLE` |
| `playsport_crowd` | 台灣社群投注選票 | 台灣運彩熱門賽事 | 讓分, 不讓分, 大小 | 15 分鐘 | 本地 Scraper 快取 | 否 | 支援快照時間戳與投票總數 | 支援快照記錄 | MEDIUM (僅代表散戶情緒) | 樣本數低於門檻 (<20) 時標註 `INSUFFICIENT_SAMPLE` |
| `playsport_expert` | 台灣運彩認證大神主推 | 台灣運彩熱門賽事 | 讓分, 不讓分, 大小 | 15 分鐘 | 個人預測頁驗證 Scraper | 否 | 支援達人發布時間 (精確度標記) | 支援達人歷史勝率回溯 | MEDIUM (僅代表個人主觀判斷) | 達人未達歷史場次 (>10 場) 則不計入推薦資格 |

---

## 2. 候選評估來源 (Future Candidates)

| 來源識別碼 | 分類 | 覆蓋評估 | 授權與存取合法性 | 整合決策與理由 |
| :--- | :--- | :--- | :--- | :--- |
| `betfair_exchange` | 國際對沖交易所市場 | 涵蓋全球足球、網球與部分美巡賽事 | API 需特定地域商業協議與高額開發者授權金，台灣 IP 存取受限 | **列為後續候選**：現階段缺乏合法無障礙公開端點，不作為 Phase 4 強制依賴。 |
| `polymarket` | 預測市場 (Prediction Market) | 政治、科技與少數熱門超級盃/總冠軍期貨，常態日常賽事讓分盤嚴重不足 | 去中心化契約公開，但常態單場賽事流動性極度碎片化 | **列為後續候選**：流動性不足與市場契約難以和台彩盤口標準化對齊。 |
| `kalshi` | CFTC 監管事件合約 | 美國宏觀事件為主，近年新增部分體育勝負市場 | 需美國合法交易帳戶與特製金鑰 | **列為後續候選**：海外註冊限制與契約非十進位標準賠率。 |

---

## 3. 資料欄位標準契約 (Data Contract)

所有進入系統之國際市場情報必須符合以下欄位約定，不得以預設值覆蓋未知數據：

### 3.1 賠率快照 (`MarketOddsSnapshot`)
- `source_id`: 來源系統 ID (string)
- `source_type`: 來源類型 (`BOOKMAKER` | `CONSENSUS` | `SYNTHETIC_FIXTURE`)
- `event_id`: 外部賽事 ID (string)
- `league`: 運動聯盟代碼 (`MLB`, `NBA`, `NFL`, `EPL`, `LALIGA`)
- `home_team`: 主隊標準英文名稱
- `away_team`: 客隊標準英文名稱
- `start_time_utc`: 比賽開始 UTC 時間 (ISO-8601)
- `market_type`: 玩法類型 (`MONEYLINE` | `SPREAD` | `TOTAL`)
- `selection`: 下注選項 (`home`, `away`, `draw`, `over`, `under`)
- `line`: 盤口數值 (如讓分 `-1.5`、大小分 `8.5`；無門檻之獨贏盤為 `null`)
- `decimal_odds`: 十進位賠率 (float $\ge 1.0$)
- `observed_at_utc`: 國際盤口發布或觀測時間 (ISO-8601)
- `retrieved_at_utc`: 本系統成功取得時間 (ISO-8601)
- `freshness_status`: 時效性狀態 (`LIVE` | `FRESH` | `AGING` | `STALE` | `UNKNOWN`)
- `evidence_url`: 資訊佐證網址 (URL 或 `null`)
- `source_license`: 資料授權標示 (string 或 `null`)
- `is_synthetic`: 是否為未配置 API Key 時產生之測試 Fixture (boolean)

### 3.2 投注傾向快照 (`BettingSplitsSnapshot`)
- `bet_percentage`: 投注張數佔比 ($0.0 \sim 100.0$，未知保留 `null`)
- `money_percentage`: 投注金額佔比 ($0.0 \sim 100.0$，未知保留 `null`)
- `sample_size`: 樣本張數或籌碼指標 (整數或 `null`)
- `reporting_bookmaker`: 回報之國際博彩公司 (string 或 `null`)
- `reporting_scope`: 統計範圍 (如 `"US_COMMERCIAL"`, `"VEGAS_RETAIL"`)

---

## 4. 異常處理與合規承諾

1. **零付費依賴**：系統預設在無任何付費金鑰之本機環境中仍可進行完整模擬回歸與單元測試。
2. **反偽造原則**：若無法取得即時投注金額比例，系統嚴格標示為 `null`，絕不將投注張數百分比或社群投票數假造為金額比例。
3. **無降水即無 EV**：若無法由市場對手盤算出無抽水（No-vig）公允機率，該筆賽事嚴格禁止標註為 `+EV`。
