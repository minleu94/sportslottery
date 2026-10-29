@echo off
chcp 65001 > nul
title 台灣運彩 瘋狗流 LINE Bot 互動伺服器
echo 正在啟動 LINE Bot 伺服器與 Cloudflare 通道...
python scripts\serve_line_bot.py
pause
