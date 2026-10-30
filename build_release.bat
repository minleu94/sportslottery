@echo off
cd /d "%~dp0"
python scripts\dev_runner.py --build-only
python -m PyInstaller --clean --noconfirm sportslottery.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
copy /y dist\sportslottery.exe sportslottery.exe > nul
echo [OK] Build successful! Generated sportslottery.exe
pause
