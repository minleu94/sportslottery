@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 正在啟動台灣運彩瘋狗流系統匣服務...
start "" pythonw scripts\tray_manager.py
echo 服務已在右下角系統匣啟動，您可以關閉此視窗。
exit
