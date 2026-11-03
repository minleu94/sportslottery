# 架構文件索引

本索引列出目前維護的架構與工程規則。實際執行行為以程式碼為準；文件描述責任邊界與長期契約。

## 主要入口

- [目前架構概觀](01-target-architecture.md)
- [目前專案狀況](../STATUS.md)
- [維運指南](../DEPLOYMENT_AND_RECOVERY.md)
- [朋友安裝指南](../INSTALL_FOR_FRIENDS.md)

## 邊界與契約

- [API 路由與服務生命週期](02-api-boundaries.md)
- [市場資料邊界與離線回放](03-market-boundaries.md)
- [共享契約與依賴邊界](04-shared-contracts.md)
- [儲存路徑與測試隔離](05-storage-boundaries.md)
- [React 與 API 回應契約](06-ui-api-contracts.md)
- [依賴、鎖檔與測試資料治理](07-governance.md)

## 架構決策

- [ADR-0001：漸進式模組單體](adr/0001-modular-monolith.md)
- [ADR-0002：資料與相容性邊界](adr/0002-data-and-compatibility-boundaries.md)
- [ADR-0003：市場證據與前瞻 cohort](adr/0003-market-evidence-boundary.md)

長期規則另見[來源能力矩陣](../SOURCE_CAPABILITY_MATRIX.md)、[台灣運彩結算規則](../TAIWAN_SETTLEMENT_RULES.md)、[模型接受與校準規則](../MODEL_ACCEPTANCE_AND_CALIBRATION.md)及[影子評估治理規則](../SHADOW_EVALUATION_GOVERNANCE.md)。

## 其他工程參考

- [串關搜尋完整性](../PARLAY_SEARCH_COMPLETENESS.md)
- [Playsport 來源身份診斷](../PLAYSport_SOURCE_HEALTH.md)
- [CLV 與建議重播](../clv_and_recommendation_replay.md)
- [研究流程](../research_pipeline.md)
