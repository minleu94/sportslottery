# ADR-0001：以漸進式模組邊界整理單體

- **狀態：** Accepted
- **日期：** 2026-11-02
- **範圍：** Sportslottery backend、桌面入口與研究流程

## 背景

目前同一應用程式同時支援 FastAPI/React、Streamlit、CLI/排程與 Windows Tray。主要業務模組留在 `core/`，provider adapters 位於 `integrations/`，但靜態匯入存在 `core ↔ integrations` 雙向邊、數個 strongly connected components，API 與 orchestration 模組也承擔多項責任。一次搬遷整個目錄會同時影響啟動、測試、序列化和 Windows 發行。

## 決策

採用漸進式 Modular Monolith：以明確契約、依賴方向及小型相容 facade 逐步改善責任邊界。現有目錄只在某個邊界已被測試保護且搬動能實際降低耦合時才調整。每個功能仍在同一 Python 程序與部署中運作。

新改動遵循 Presentation → Application → Domain/Contracts 的呼叫方向。外部 provider 與儲存由組裝入口注入，adapter 不反向呼叫應用流程。因現有位置混合不同層次，M3–M8 以實際模組責任判斷，而不只看 package 名稱。

## 後果

- router、provider、eligibility 等責任可逐批拆出，且每批均能單獨回退。
- 仍會暫時看到舊路徑與 facade；它們是遷移相容機制，須記錄 owner 和移除條件。
- 只有完成相應測試後，才新增禁止依賴的 CI 守門。
- 不引入額外服務、資料庫或通訊基礎設施。

## 回退

回退單一 milestone commit，保留先前公開 import 與 endpoint。程式回退不修改 SQLite schema、既有 snapshots 或外部資料根目錄。
