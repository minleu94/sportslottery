# Frontend

React、TypeScript 與 Vite 的前端原始碼位於此目錄，對接 FastAPI 開發介面。repo 目前的桌面安裝包使用 Streamlit 入口，不包含這個 React 前端。

## 開發與建置

安裝鎖定的 npm 套件：

    npm ci

啟動 Vite 開發伺服器：

    npm run dev

建置正式前端資產：

    npm run build