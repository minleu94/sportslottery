# 本機專案埠號對照

| 專案／用途 | 本機位址或埠 | 說明 |
| --- | --- | --- |
| daily_stock_analysis Web/API | http://127.0.0.1:8000 | 保留原有預設 |
| daily_stock_analysis Vite 開發前端 | http://127.0.0.1:5173 | 僅前端開發時使用 |
| Sportslottery 現代介面與 API | http://127.0.0.1:8100 | 桌面、手機與 LINE 共用服務 |
| Sportslottery Vite 開發前端 | http://127.0.0.1:5174 | 僅前端開發時使用，API 代理至 8100 |
| Sportslottery 舊版 Streamlit | http://127.0.0.1:8501 | 現有桌面發布版本；與現代版為不同入口 |
| IG Tracking / InkScope | http://127.0.0.1:8200 | 本機啟動器；手動 uvicorn 須指定埠 |
| Risk Lab Journal | http://127.0.0.1:8765 | 預設；受占用時啟動器可能使用其他埠，依啟動器顯示為準 |
| Moomoo OpenD | 127.0.0.1:11111 | Risk Lab 行情連線，非網頁 |
| Sportslottery 系統匣程序鎖 | 127.0.0.1:28501 | 程序協調，非網頁 |

這是本機使用約定，不能保證其他程式不會占用。`localhost` 與 `127.0.0.1` 通常指向本機；網址中的埠號用來區分服務。修改前請同步檢查啟動器、代理、CORS、tunnel 與 OAuth callback。已運行的程序需要重啟才會套用設定。Risk Lab 的啟動器在預設埠無法使用時可向後搜尋備用埠；不要依賴備用埠固定不變。

現代版可用 `start_dev.bat` 或 `start_modern.ps1`；手機啟動與系統匣共用 8100，不要同時開啟第二個相同服務。重新編譯 EXE 前，既有打包檔仍使用打包時的舊設定。舊版 Streamlit 使用 8501。自訂 Cloudflare／ngrok 上游如寫死舊埠，須同步改為 8100。

## 2026-11-05 調整紀錄

現代版從 8000 改為 8100，Vite 從 5173 改為 5174；同步修改系統匣、開發及手機啟動、API、Vite 代理、CORS 和 LINE 內網連結。原有 Streamlit 發布版仍為 8501。程式重啟後才套用；既有 EXE 沒有在本次重新打包，可能仍使用舊埠，須先依發布流程重新打包及驗證。自訂遠端 tunnel 若寫死舊埠也須同步更新。

日後更動埠號，請同步更新四個專案的 `LOCAL_PORTS.md`，並驗證本機、手機／LINE 與使用中的 tunnel。
