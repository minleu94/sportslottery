# API 路由與服務生命週期

**狀態：** M3 完成實作，待跨平台 CI 驗收

## Composition root

`server/api.py` 保留 `server.api:app`，建立單一 FastAPI app、設定 CORS/security headers、掛載 router 與既有靜態資產。它不再放置各業務 endpoint 實作。

| 模組 | 所有權 | 路徑範圍 |
| --- | --- | --- |
| `server/routers/market.py` | 狀態、雷達、台彩腿、market research、Odds API 設定與操作 | `/api/health`, `/api/radar`, `/api/legs`, `/api/market/*` |
| `server/routers/parlay.py` | 串關 request、同請求 coalescing、signal preparation cache 與回應格式 | `/api/parlays/search` |
| `server/routers/wallet.py` | 錢包與注單讀寫 | `/api/wallet/*`, `/api/tickets*` |
| `server/routers/identity.py` | Profile、登入/登出、PIN、管理員功能 | `/api/profiles/*`, `/api/auth/*`, `/api/admin/*` |
| `server/routers/research.py` | 前瞻 analytics 與管理員 storage 狀態 | `/api/research/*`, `/api/system/storage_status` |
| `server/routers/line.py` | LINE webhook 簽章、事件處理與去重 | `/callback` |

Router 不匯入 `server.api`；它們只依賴 service registry、auth、request schemas、presentation formatter 及既有業務服務。`server.api` 額外 re-export 原常用函式、schemas 和 `_line_notifier`，以維持舊 import 入口。Router 測試應 mock 實際責任模組或 `server.service_registry`，不 mock composition root 的內部全域狀態。

## Service registry 與生命週期

`server/service_registry.py` 定義 `ServiceBundle` 為 tuple-compatible `NamedTuple`，欄位依序維持舊八項服務順序：odds adapter、signal hub、parlay engine、radar、profile manager、snapshot logger、metrics engine、shadow portfolio。既有 tuple unpacking 不需改寫，新呼叫者可以用欄位名稱讀取。

單一鎖包住 lazy initialization。七項共用服務先以區域變數完整建構，再一次發布；ProfileManager 亦在返回 bundle 前可用。任何 constructor 拋錯時，呼叫端不會取得半成品。每個 router 透過同一 module registry 取得 shared instance。錢包、recorder 與 betting service 依 profile 建立，沒有放進全域 shared bundle。

`server/lifecycle.py` 保留原 scheduler startup/shutdown 行為及 `atexit` fallback。FastAPI lifespan 使用同一個 `get_market_scheduler()` singleton；沒有新增 worker、背景排程或第二個 app。

## 合約與回歸證據

- `tests/fixtures/contracts/api_routes.json` 是重構前由 `server/api.py` decorator 讀出的 38 組 HTTP path/method。
- `tests/test_api_contract.py` 對照執行中 `app.openapi()` 的 path/method，並驗證市場、串關、登入、註冊、下注、結算與存款 request model reference。
- `tests/test_service_registry.py` 驗證 12 條並行呼叫只建立一份 shared service bundle，並模擬 constructor 失敗確認沒有發布半成品。
- 既有 `test_modern_api.py`、`test_market_api.py`、`test_market_scheduler.py`、`test_phase1_security.py`、`test_phase2_betting_integrity.py` 持續驗證 API/Auth/Admin/Wallet/Market 行為；內部 monkeypatch 已改到路由或 service registry 的實際 owner。

OpenAPI 的 path/method、request model 與既有 route assertions 可覆蓋本次拆分風險；沒有改 endpoint、HTTP method、response code、session dependency、CORS、security headers 或 response serialization。
