# 市場資料邊界與離線回放

## 呼叫責任

`MarketForwardPipeline` 仍是舊呼叫者使用的相容 orchestration 入口。候選資格判斷位於純政策函式 `core/market_candidate_policy.py`；它不抓取資料、不發送請求，也不寫入快照。Market pipeline 接收 Taiwan odds provider、international odds provider、SignalHub、MarketAligner、fair odds engine 與 snapshot logger；沒有注入其中一個 provider 時，才透過 `core/market_provider_factory.py` 建立該預設 adapter。

一次市場週期按以下順序執行：

1. 依賽事 ID、台彩盤口新鮮度、Synthetic 狀態、UTC 開賽時間、聯賽／運動、隊伍、玩法、選邊、線位與賠率篩選候選。
2. 只按通過篩選的候選分組查詢國際市場；保留查詢成本及配額診斷。
3. 以市場對齊器確認事件、時間、玩法和線位。
4. 以完整且通過來源、對手盤與時間檢查的報價建立 `MarketBenchmarkEvidence`。
5. 將合格市場基準注入 SignalHub，再產生推薦資料及 snapshot。

過期或格式不完整的台彩候選不參與市場對齊、SignalHub 評估或 snapshot；拒絕原因保留於週期診斷。

## Golden replay

`tests/fixtures/market/mlb_moneyline_replay.json` 是版本控制中的固定輸入，不含帳戶金鑰或正式使用者資料。測試把 fixture 的觀察時間固定，使用離線 provider stub、正式 MarketAligner、fair odds engine、SignalHub 及指向暫存目錄的 PredictionSnapshotLogger。它比對：

- 有效候選數、唯一賽事數與真實匹配數。
- 同一莊家完整雙向市場的去水機率及台彩理論 EV。
- 國際市場來源資格及不重複建立 Sharp 訊號投票。
- snapshot 的賽事、開賽時間、機率、EV、驗證資格、待結算狀態及來源 lineage。
- snapshot hash 可由已記錄的 hash 輸入重新計算。

fixture 的預期機率為 0.525，台彩賠率為 2.0，因此市場基準 EV 為 0.05。測試不連線 The Odds API、不消耗 API credits，快照只寫入 pytest 暫存目錄。

這個 replay 只驗證 fixture 所代表的 MLB moneyline 路徑。其他盤型的離線案例由 `test_market_benchmark_integration.py`、`test_market_aligner.py` 與 `test_market_fair_odds.py` 覆蓋；任何離線測試成功都不代表即時來源或真實配額已驗收。

## 回退與資料保護

若 M4 回歸，回退 M4 程式碼並重跑原有 pipeline 測試即可。變更不執行 snapshot 遷移、結算重播或資料刪除。正式 `data` Junction 不應作為此 replay 的輸入或輸出位置。
