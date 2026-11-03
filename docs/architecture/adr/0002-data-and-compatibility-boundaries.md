# ADR-0002：保留資料、路徑與外部相容性

- **狀態：** Accepted
- **日期：** 2026-11-02
- **範圍：** SQLite、JSONL、檔案路徑、API、UI 與 Windows 啟動

## 背景

錢包/Profile、研究 ledger、snapshot 與 cache 使用既有 SQLite/JSONL/檔案路徑。此工作樹的 `data` 為指向外接磁碟的 Windows Junction。API、Streamlit、LINE、CLI 與打包入口仍被不同使用者和測試引用；僅從 README 不能確認某個入口已退役。

## 決策

1. 重構測試只使用隔離的暫存目錄與資料庫；禁止用正式 `data` 路徑寫入。
2. 保持 SQLite schema、JSONL 欄位與 snapshot lineage 不變。不得以搬遷正式資料作為模組拆分手段。
3. path resolution 由目前 `core.storage_config`、`core.research_paths` 等既有 contract 控制；若後續固定解析結果或包成 storage object，先測 Windows Junction、symlink、相對/絕對設定及 protected-root guard。
4. API path、HTTP method、status、response schema、Session/RBAC、CORS/security headers 與前端操作流程是相容性基準。
5. `server.api.app`、舊 module import、Streamlit、LINE 與 Windows launcher/spec 在替代入口完成跨平台 smoke test 前不得移除。

## 驗收與回退

以 schema/OpenAPI 比對、temp-database atomicity、backup/restore 驗證及目錄解析測試守護相容性。任何 path、schema 或 HTTP contract 變更都需要獨立證據和明確相容層；若無法證明可逆，就不做該變更。
