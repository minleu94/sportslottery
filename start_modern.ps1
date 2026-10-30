<#
.SYNOPSIS
    台灣運彩「瘋狗流」高倍串關系統 - Modern Edition 啟動腳本
#>

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " 🐕 台灣運彩「瘋狗流」決策系統 - Modern Edition (v2.3.0 Dev)" -ForegroundColor Green
Write-Host " React + TypeScript + Tailwind CSS + shadcn/ui + FastAPI" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$distIndex = Join-Path $PSScriptRoot "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
    Write-Host "[1/2] 正在首次建置前端 SPA 靜態資源..." -ForegroundColor Yellow
    Push-Location (Join-Path $PSScriptRoot "frontend")
    npm.cmd run build
    Pop-Location
} else {
    Write-Host "[1/2] 前端 SPA 已就緒。" -ForegroundColor Green
}

Write-Host "[2/2] 正在啟動 FastAPI 後端與靜態伺服器 (http://127.0.0.1:8000)..." -ForegroundColor Cyan
Start-Process "http://127.0.0.1:8000"

python -m uvicorn server.api:app --host 127.0.0.1 --port 8000 --reload
