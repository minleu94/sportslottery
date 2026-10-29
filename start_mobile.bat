@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python scripts\serve_mobile.py %*
) else (
    where py >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        py -3 scripts\serve_mobile.py %*
    ) else (
        echo [ERROR] Python was not found in PATH.
        pause
        exit /b 1
    )
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Server exited with code %ERRORLEVEL%.
    pause
)
