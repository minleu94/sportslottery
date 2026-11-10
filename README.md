# 台灣運彩「瘋狗流」決策系統

Sportslottery 是一套本機運彩研究與注單記錄工具，用賽事資料、台灣運彩盤口和其他情報協助使用者檢視串關候選。它不會代替使用者下注，也不保證預測準確或獲利。

模型機率目前仍未完成實證校準；HIGH 表示情報支持程度，不代表固定勝率。資料來源的可用性與新鮮度會隨時間改變，請以程式當下顯示的來源狀態為準。

本機網址與其他專案的埠號分配見[本機埠號對照](docs/LOCAL_PORTS.md)。

## 開始使用

- 朋友安裝：請看[朋友安裝指南](docs/INSTALL_FOR_FRIENDS.md)。
- 開發、發布、研究流程、排程與資料備份：請看[維運指南](docs/DEPLOYMENT_AND_RECOVERY.md)。

## 專案文件

- [目前狀況與已知限制](docs/STATUS.md)：只說明目前有效的狀況，不記錄歷程或待辦計畫。
- [變更紀錄](CHANGELOG.md)：用簡短日期條目記錄已完成的改動。
- [架構索引](docs/architecture/README.md)：架構概觀、模組邊界與 ADR。
- [Repository 治理與品質閘門](docs/REPOSITORY_GOVERNANCE.md)：版本、發布、資料與保留政策。
- [CI 驗收證據](docs/QUALITY_GATES.md)：離線測試涵蓋範圍及真實資料驗收界線。
- [安全性政策](SECURITY.md)：安全邊界、必須成立的授權條件與回報方式。
- [來源能力矩陣](docs/SOURCE_CAPABILITY_MATRIX.md)：來源整合能力及資料契約。
- [台灣運彩結算規則](docs/TAIWAN_SETTLEMENT_RULES.md)：玩法與結算規則。
- [研究流程](docs/research_pipeline.md)：影子研究流程與執行方式。
- [模型接受與校準規則](docs/MODEL_ACCEPTANCE_AND_CALIBRATION.md)。
- [影子評估治理規則](docs/SHADOW_EVALUATION_GOVERNANCE.md)。

## 開發

程式庫保留 Streamlit 桌面介面與 FastAPI／React 開發介面；目前 Release 工作流程打包的是 Streamlit 版本。兩條啟動路徑的現況見[目前狀況](docs/STATUS.md)，開發與 CI 規範見[架構索引](docs/architecture/README.md)。
