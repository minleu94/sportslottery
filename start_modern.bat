@echo off
chcp 65001 > nul
title 台灣運彩「瘋狗流」決策台 (Modern Edition)

echo ========================================================
echo  🐕 台灣運彩「瘋狗流」決策系統 - Modern Edition (v2.0)
echo  React + TypeScript + Tailwind CSS + shadcn/ui + FastAPI
echo ========================================================
echo.

:: 檢查前端是否已建置
if not exist "frontend\dist\index.html" (
    echo [1/2] 正在首次編譯現代前端 SPA...
    cd frontend
    call npm.cmd run build
    cd ..
) else (
    echo [1/2] 前端 SPA 已就緒。
)

echo [2/2] 正在啟動 FastAPI 本機伺服器 (http://127.0.0.1:8000)...
echo.
echo 系統即將於預設瀏覽器中自動開啟...
echo.

:: 延遲 1.5 秒自動於瀏覽器開啟
start "" timeout /t 2 /nobreak > nul ^& start http://127.0.0.1:8000

:: 啟動 Uvicorn 伺服器
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000

pause
