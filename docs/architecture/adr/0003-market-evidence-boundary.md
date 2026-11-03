# ADR-0003：市場證據與前瞻 cohort

- **狀態：** Accepted
- **日期：** 2026-11-02
- **範圍：** MarketForwardPipeline、ResearchPipeline、SignalHub、snapshots 與 evaluation

## 背景

MarketForwardPipeline 已把驗證過的 `MarketBenchmarkEvidence` 傳入 SignalHub，再寫入有 hash/lineage 的 snapshot，並可呼叫賽果結算與 forward evaluation。獨立 ResearchPipeline 使用另一個資料根目錄和研究 cohort。市場證據型別位於 `integrations/odds/market_models.py`，但同時被 core policy 和 provider adapter 使用，呈現出契約 ownership 不明的問題。

## 決策

- 一筆國際報價只可透過一份合格 `MarketBenchmarkEvidence` 進入決策；Sharp 只能表示來源政策資格，不是另一個額外市場投票。
- Taiwan candidate、國際 event、market、selection/line、來源、觀察時間、取得時間、Synthetic 狀態與拒絕原因要分開保留，不能以預設值填補缺失證據。
- MarketForward 與 Research 是不同資料 cohort。未來可以共用 pure policy 和穩定序列化契約，但不得因此合併 schema、快照或樣本數。
- M4 先建立離線 Golden replay 再調整 orchestrator。M5 再考慮把通用 contract 從 provider module 搬到 core-owned contract module，並保留原 import re-export。
- EV、去水、公允機率、line convention、sample eligibility、Brier/ROI/CLV 與模型接受數學定義不因架構拆分而變動。

## 後果

市場來源的錯誤可定位於 provider parsing、qualification、alignment 或 decision，而不會被匯總為單一「LIVE」狀態。Golden replay 比對和來源 lineage 可能需要額外 fixture，但不消耗正式 API credits。
