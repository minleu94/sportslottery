# 🐕 台灣運彩「瘋狗流」決策系統 —— 全功能與 LINE Bot 移交維運手冊
> **專為未來接手 Agent、開發者與維運人員撰寫的完整系統交接文檔**  
> **更新日期**：2026-10-30 | **策略版本**：v2.0-research | **系統狀態**：正式上線運行中

---

## 目錄
1. [專案核心理念與定位](#1-專案核心理念與定位)
2. [系統總體拓撲架構圖](#2-系統總體拓撲架構圖)
3. [網路端口與隧道通訊規範（三大專案隔離隔離機制）](#3-網路端口與隧道通訊規範三大專案隔離機制)
4. [LINE Bot 官方帳號機器人全功能詳解](#4-line-bot-官方帳號機器人全功能詳解)
   - [互動架構與 Webhook 同步](#41-互動架構與-webhook-同步)
   - [LINE 完整觸發關鍵字與指令表](#42-line-完整觸發關鍵字與指令表)
   - [快捷回覆按鈕 (Quick Reply)](#43-快捷回覆按鈕-quick-reply)
   - [彩券行 3.0 QR Code 投注單產製機制](#44-彩券行-30-qr-code-投注單產製機制)
   - [多玩家 Profile 隔離與 PIN 碼安全系統](#45-多玩家-profile-隔離與-pin-碼安全系統)
5. [Streamlit 決策台與手機 PWA Web App](#5-streamlit-決策台與手機-pwa-web-app)
6. [後端核心演算與風控大腦](#6-後端核心演算與風控大腦)
7. [Windows 系統匣（Tray Manager）與常駐服務](#7-windows-系統匣tray-manager與常駐服務)
8. [設定檔與資安邊界（重要：防洩漏規範）](#8-設定檔與資安邊界重要防洩漏規範)
9. [接手 Agent 維運與排錯指南 (Troubleshooting)](#9-接手-agent-維運與排錯指南-troubleshooting)

---

## 1. 專案核心理念與定位

本系統不是宣稱能通靈預測的「黑盒子賭神 AI」，而是**一套專為台灣運動彩券設計的情報聚合器、正期望值 (+EV) 串關演算器與資金風控引擎**。

* **核心價值主張**：
  1. **以小博大**：聚焦在 **10x ～ 500x** 目標倍率的高賠率串關組合。
  2. **鐵壁風控**：永遠把每週外部新增入金嚴格鎖定在 **NT$ 200** 娛樂預算（每週一自動重置額度）。
  3. **獲利鎖定（Prize Pool）**：一旦串關中獎，所有派彩獎金全數自動匯入「獲利保留池」，非經手動提領絕不隨意吐回再下注，落實「只用零錢博大獎、贏錢全數鎖利」。
  4. **全端無縫串接**：支援「電腦瀏覽器 + 手機 Safari PWA + LINE 官方機器人 + 彩券行機台 1 秒 QR 掃描出票」。

---

## 2. 系統總體拓撲架構圖

```
                      ┌──────────────────────────────────────┐
                      │          使用者行動端 / 外部連線         │
                      └──────────────────┬───────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 │                                               │
        (LINE 訊息 / 語意指令)                                (手機 Safari / 電腦 Web)
                 │                                               │
                 ▼                                               ▼
     ┌────────────────────────┐                     ┌────────────────────────┐
     │ Cloudflare QuickTunnel │                     │ ngrok 永久固定專屬網域 │
     │ (由本機開機 API 自動註冊)│                     │ (Dev Domain 永不失效)  │
     └───────────┬────────────┘                     └───────────┬────────────┘
                 │ (HTTPS)                                      │ (HTTPS)
                 ▼                                              ▼
   [本機 Port 8001: FastAPI Webhook]              [本機 Port 8501: Streamlit 決策台]
                 │                                              │
                 ├───────────────────────┬──────────────────────┤
                 │                       │                      │
                 ▼                       ▼                      ▼
        ┌─────────────────┐     ┌─────────────────┐    ┌─────────────────┐
        │  LineNotifier   │     │   Signal Hub    │    │ WeeklyWalletMgr │
        │  (指令解析/回覆) │     │ (大神/盤口/社群) │    │ (每週200風控池) │
        └────────┬────────┘     └────────┬────────┘    └────────┬────────┘
                 │                       │                      │
                 ▼                       ▼                      ▼
        ┌─────────────────┐     ┌─────────────────┐    ┌─────────────────┐
        │ ProfileManager  │     │  ParlayEngine   │    │  LotteryQRCode  │
        │ (4位PIN多玩家DB) │     │ (+EV與凱利注碼) │    │ (台彩3.0掃描碼) │
        └─────────────────┘     └─────────────────┘    └─────────────────┘
                                         ▲
                                         │ (本機守護進程託管)
                 ┌───────────────────────┴───────────────────────┐
                 │       Windows 系統匣管理員 (Tray Manager)      │
                 │       - 監聽 Port 28501 (單實例鎖)             │
                 │       - 無終端機黑視窗背景運行                   │
                 │       - 右下角系統匣圖示 (綠色小狗)             │
                 └───────────────────────────────────────────────┘
```

---

## 3. 網路端口與隧道通訊規範（三大專案隔離機制）

> [!CAUTION]
> **接手 Agent 必讀之本機網路規範（嚴禁觸犯）**：
> 1. 本機另有獨立專案 `ig_tracking (inkscope)`，固定佔用 **Port 8000** 並透過 Tailscale Funnel 提供外部服務。**任何情況下絕對不可佔用 Port 8000，且絕對不可修改 `tailscale serve` 或 `tailscale funnel`！**
> 2. 本專案一律使用 **Port 8001**（LINE Webhook）與 **Port 8501**（Streamlit 決策台）。

### 端口與通道對照表

| 服務項目 | 本地監聽端口 | 對外公網通道方案 | 網址特性 | 設定依賴 |
| :--- | :--- | :--- | :--- | :--- |
| **Streamlit 決策台** | `http://127.0.0.1:8501` | **ngrok 官方客戶端** | **永久固定 Dev Domain**<br>(`https://fifty-saddlebag-immortal.ngrok-free.dev`) | `config/ngrok_config.yaml`<br>`%LOCALAPPDATA%\ngrok\ngrok.yml` |
| **LINE Bot Webhook** | `http://127.0.0.1:8001` | **Cloudflare Quick Tunnel** | 每次開機自動取得臨時網址，**程式啟動時透過 LINE API 自動註冊更新** | `cloudflared.exe`<br>`config/line_notifier.yaml` |
| **系統匣單實例鎖** | `127.0.0.1:28501` | 僅限本地 Loopback | 防止雙擊重複啟動程式進程 | `scripts/tray_manager.py` |
| *(外部專案 inkscope)* | *127.0.0.1:8000* | *Tailscale Funnel* | *獨立專案專用，本專案嚴禁碰觸* | *無關* |

---

## 4. LINE Bot 官方帳號機器人全功能詳解

### 4.1 互動架構與 Webhook 同步
- **進入點**：`scripts/line_webhook_server.py`（FastAPI 驅動）
- **核心控制類**：`core/line_notifier.py`（`LineNotifier`）
- **0 成本原則**：所有回覆訊息一律使用 LINE Webhook 提供之 `replyToken` 呼叫 `https://api.line.me/v2/bot/message/reply`，**完全不消耗任何官方帳號付費 Push 訊息額度（終身免費回覆）**。
- **自動註冊機制**：當執行 `scripts/serve_line_bot.py` 時，程式會取得 Cloudflare 產生的安全 HTTPS 網址，並透過 `PUT https://api.line.me/v2/bot/channel/webhook/endpoint` 直接向 LINE 官方伺服器登記，使用者與開發者皆**完全無須手動至後台複製貼上 Webhook**。

---

### 4.2 LINE 完整觸發關鍵字與指令表

使用者在 LINE 官方帳號對話框輸入文字，或點選下方按鈕，系統依循以下模式解析：

| 功能類別 | 觸發關鍵字 / 輸入範例 | 系統回覆與行為說明 |
| :--- | :--- | :--- |
| **主功能表** | `功能表`、`選單`、`menu`、`help`、`說明`、`你好`、`開始`、`？` | 展開完整的指令操作指南與功能介紹，並附帶 Quick Reply 按鈕。 |
| **智慧串關推薦** | `20倍`、`20`、`50倍`、`100x`、`2.5倍`、`串關` | 自動從今日開盤場次中，依據勝率與 +EV 演算法配對出目標倍率的最佳串關，並附帶 **1/4 凱利公式建議注碼**。 |
| **指定球種串關** | `足球 20倍`、`棒球 10倍`、`籃球 50倍`、`美足 15倍` | 鎖定特定運動種類，搜尋出符合目標倍率的單一球種串關。 |
| **穩健保底組** | `高勝率`、`保底`、`穩健`、`銀行家`、`banker` | 快速產出賠率在 2.0x ~ 3.0x 之間的高信心定海神針組合。 |
| **彩券行 QR 碼** | `qr`、`產qr`、`條碼`、`投注單`、`qrcode`、`出票` | 為上一筆推薦的串關組合即時生成台灣運彩 3.0 機台專用條碼（PNG 圖片直發），彩券行 1 秒掃碼出票免手劃單。 |
| **資產與戰績** | `查戰績`、`戰績`、`錢包`、`餘額`、`本週`、`本金`、`獲利` | 回傳當前玩家的：本週可用餘額（NT$200限額）、已下注額、中獎保留儲備池、歷史總淨利。 |
| **今日開盤雷達** | `今日開盤`、`開盤`、`雷達`、`今天`、`賽程`、`賽事` | 回傳「賽季雷達 (Season Radar)」簡報，標示 MLB、NFL、英超、CPBL、NPB 等今日綠燈開盤場次。 |
| **聽牌對沖保本** | `對沖`、`對衝`、`聽牌`、`鎖利`、`保本` | 掃描本機已投注且尚未結算的注單。若串關只剩最後一關未打，即時算出反向對沖注碼，達到 **100% 鎖利** 或 **0 虧損保本**。 |
| **個人設定導覽** | `個人設定`、`帳號`、`切換玩家`、`我的設定` | 顯示當前玩家身分、每週預算限額、公網決策台登入專屬連結（帶有使用者參數）。 |
| **綁定 LINE 身分** | `綁定 <玩家名稱> <4位PIN>`<br>*(例：`綁定 Tony 0000`)* | 將目前這支手機的 LINE User ID 與本機 SQLite Profile 永久綁定，之後此手機發言皆自動歸屬該玩家。 |
| **切換操作玩家** | `切換 <玩家名稱> <4位PIN>`<br>*(例：`切換 小明 1234`)* | 即時切換目前操作的工作玩家，後續下注與戰績將計入該玩家錢包。 |
| **新增玩家帳號** | `新增 <名稱> [預算] [PIN]`<br>*(例：`新增 Alex 200 8888`)* | 在本機資料庫創建全新獨立的玩家，並分配每週 NT$200 獨立娛樂錢包。 |
| **修改安全 PIN** | `改密碼 <舊PIN> <新PIN>`<br>*(例：`改密碼 0000 1234`)* | 直接在 LINE 聊天室變更該玩家的 4 位數登入 PIN 碼。 |
| **調整每週預算** | `預算 <金額>`<br>*(例：`預算 300`)* | 調整目前玩家每週可投入的外部金額（預設為 NT$ 200）。 |

---

### 4.3 快捷回覆按鈕 (Quick Reply)
每當使用者發送訊息，LINE Bot 回傳訊息下方皆會附帶「即刻點擊」快捷按鈕列表（`core/line_notifier.py` -> `default_quick_replies()`）：
1. 📱 **產生投注 QR 碼** (`QR`)
2. 🎯 **找20倍串關** (`20倍`)
3. 🔥 **找50倍高賠** (`50倍`)
4. 💰 **查戰績錢包** (`查戰績`)
5. 👤 **玩家登入/設定** (`個人設定`)
6. ☀️ **今日開盤** (`今日開盤`)
7. 🛡️ **聽牌對沖** (`對沖`)

---

### 4.4 彩券行 3.0 QR Code 投注單產製機制
- **模組路徑**：`core/lottery_qr.py`
- **運作流程**：
  1. 將推薦之賽事（聯賽、場次代號、玩法、客主隊、投注選項、賠率）依台灣運彩 3.0 規格編碼為投注資料字串。
  2. 透過 `qrcode` 套件在本地 `static/qr/` 生成高解析度條碼 PNG。
  3. 透過 FastAPI `/static/qr/<filename>.png` 靜態檔案路由提供外部存取。
  4. LINE Bot 直接以 `image` 訊息類型推送條碼圖片至聊天室。
  5. 使用者走進彩券行，直接持手機條碼對準投注機紅外線掃描口，「嗶」一聲即可印出彩券，免手寫劃單！

---

### 4.5 多玩家 Profile 隔離與 PIN 碼安全系統
- **資料庫路徑**：`data/sportslottery.db`（SQLite，由 `core/profile_manager.py` 嚴密控制）
- **核心設計**：
  - 每個玩家擁有獨立的：`weekly_play_cap`（預設 NT$200）、`pin_code`（預設 `0000`）、獨立錢包流水帳本與下注記錄。
  - 支援 LINE User ID 雙向綁定：同一台伺服器可供家庭成員、好友群共用，彼此帳目完全分離。
  - 防暴搜防護：PIN 碼必須為 4 位純數字字串。

---

## 5. Streamlit 決策台與手機 PWA Web App

- **本機位址**：`http://localhost:8501`（或 `http://127.0.0.1:8501`）
- **公網永久位址**：`https://fifty-saddlebag-immortal.ngrok-free.dev`（由 ngrok 守護進程掛載）

### 5.1 四大核心功能頁面
1. **🏠 ①「今日可玩」—— 賽季雷達 (Season Radar)**：
   - 燈號顯示：🟢 賽季進行中且今日有開盤 / 🟡 賽季中但今日無盤 / 🔴 休賽季。
   - 支援聯賽：MLB、NFL、英超、歐冠、CPBL、NPB、NBA、NHL、台灣職籃等。
2. **🔥 ②「瘋狗看盤」—— 10~500倍 情報串關台**：
   - 快捷選倍率：`10x~25x (穩健)`、`25x~75x (狂犬)`、`75x~200x (瘋狗)`、`200x~500x (極限 Moonshot)`。
   - 跨界混串（Cross-sport）：自由勾選是否跨運動項目組合。
   - 呈現 Signal Hub 四大情報支持度（市場盤口、大神主推、社群大眾、開源統計模型）。
3. **💰 ③「資金紀錄」—— 每週 NT$ 200 風控與獲利池**：
   - 顯示本週可玩、本週已注、獲利保留池、歷史損益。
   - 下注紀錄、派彩結算、手動補單、自保留池提領。
4. **📖 ④「指標與資料來源說明」**：
   - 離線可讀的 EV、賠率、勝率、凱利公式公式與白話解釋。

### 5.2 手機 iPhone Safari「加入主畫面」(PWA 體驗)
- 靜態圖示與 Manifest：已配置於 `static/manifest.json` 與 `static/pwa_icons/`。
- **免 Error 1016 原理**：過去使用 Cloudflare 臨時快速通道，每當電腦重開機網址就會更換，導致手機加入主畫面之圖示失效（報 Error 1016）。現已全面改用 **ngrok 官方永久 Dev Domain**，無論伺服器重開機多少次，網址始終固定為 `https://fifty-saddlebag-immortal.ngrok-free.dev`，手機 App 圖示永遠可用。

---

## 6. 後端核心演算與風控大腦

### 6.1 Signal Hub 情報匯流大腦 (`core/signal_hub.py`)
不依賴單一黑盒子預測，而是將四大訊號標準化：
1. **市場盤口**：台彩賠率隱含勝率。
2. **大神主推**：抓取玩運彩等公開平台之專家排行榜預測。
3. **社群大眾**：運彩社群投票支持率。
4. **開源統計模型**：球隊攻守 Elo 評分、Pythagorean 預期勝率、Poisson 泊松分布模型。
- **共識指標**：評定出 `HIGH / MED / LOW / INSUFFICIENT_SIGNAL`，嚴格模式下一律過濾掉缺乏情報支持的冷門場次。

### 6.2 串關互斥防護網 (`core/correlation_guard.py`)
- 自動偵測「同一場比賽之互斥選項」（例如同時選了 A 隊不讓分勝 + B 隊讓分勝）。
- 嚴格阻絕台灣運彩規則禁止之同場串關。

### 6.3 1/4 凱利注碼引擎 (`core/kelly.py`)
- 公式：$f^* = \frac{b \cdot p - q}{b} \times 0.25$
- 將完整凱利分數縮小為 1/4（Fractional Kelly），在追逐高倍率的同時，徹底避免賭徒破產風險，確保單注下注額符合本週 NT$ 200 預算紀律。

### 6.4 聽牌自動對沖計算器 (`core/hedging.py`)
- 當一張 $N$ 關的串關已經成功命中 $N-1$ 關，只剩最後一場尚未開打時觸發。
- 自動計算反向盤口之對沖投注金額，讓使用者能在「保證獲利」與「完全保本（0 虧損）」之間自由抉擇。

---

## 7. Windows 系統匣（Tray Manager）與常駐服務

為了避免在使用者桌面上留下多個黑色的命令提示字元 (CMD) 視窗，系統設計了精巧的常駐守護架構：

- **啟動入口**：`start_tray.vbs`（VBScript 靜音無黑窗啟動器）
- **核心守護進程**：`scripts/tray_manager.py`（基於 `pystray` 與 `Pillow`）
- **捷徑清單**：
  - 桌面捷徑：`C:\Users\archi\Desktop\台灣運彩瘋狗流.lnk`
  - 開始功能表：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\台灣運彩瘋狗流.lnk`
  - 開機自動啟動：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\台灣運彩瘋狗流.lnk`

### 系統匣功能清單（右下角綠色小狗圖示）
- **狀態顯示**：🟢 服務正常運行中 (LINE + Web) / ⚠️ 服務異常
- **🌐 開啟決策台 (電腦瀏覽器)**：直接呼叫預設瀏覽器開啟 `http://localhost:8501`。
- **📱 複製手機公網網址 (HTTPS)**：將 `https://fifty-saddlebag-immortal.ngrok-free.dev` 複製至剪貼簿，並彈出通知。
- **💬 複製 LINE Webhook 網址**：複製即時 LINE Webhook 連結。
- **🔄 重新啟動服務**：一鍵無痛重啟後端 Webhook 與 Streamlit 服務進程。
- **❌ 停止並退出服務 (Quit)**：安全結束所有背景進程並釋放端口。

---

## 8. 設定檔與資安邊界（重要：防洩漏規範）

> [!IMPORTANT]
> **接手 Agent 絕對約束條款**：
> 1. **嚴禁要求使用者在聊天對話框貼出任何私鑰、Token 或密碼！**
> 2. 所有密鑰皆只保存在本機受 `.gitignore` 保護的設定檔或使用者目錄中。

### 關鍵檔案清單與資安規範

| 檔案路徑 | 作用說明 | 是否納入 Git 版控 | 敏感度 |
| :--- | :--- | :--- | :--- |
| `config/ngrok_config.yaml` | 本機 ngrok 專屬網域設定檔 | ❌ **已 Git 忽略** | ⚠️ 中（僅含網域名稱） |
| `config/ngrok_config.example.yaml` | ngrok 設定檔範本 | ✅ 納入版控 | 🟢 公開範本 |
| `%LOCALAPPDATA%\ngrok\ngrok.yml` | ngrok 官方 Authtoken 本機金鑰 | ❌ **系統外目錄** | 🚨 極高（使用者私人金鑰） |
| `config/line_notifier.yaml` | LINE Channel Token 與通知設定 | ❌ **已 Git 忽略** | 🚨 極高（LINE 機器人金鑰） |
| `data/sportslottery.db` | 玩家帳號、4位PIN碼、下注紀錄 SQLite | ❌ **已 Git 忽略** | ⚠️ 高（使用者資產資料） |
| `data/line_bot_runtime.json` | 執行期暫存之動態網址與 PID 紀錄 | ❌ 臨時資料 | 🟢 本機暫存 |
| `data/*.log` | 服務日誌（`bot_service.log`, `streamlit_service.log`, `tray_manager.log`） | ❌ **已 Git 忽略** | 🟢 本機診斷 |

---

## 9. 接手 Agent 維運與排錯指南 (Troubleshooting)

若未來接手的 Agent 收到使用者的問題回報，請依照以下標準作業流程 (SOP) 進行排查：

### 情況 A：使用者回報「手機點開網址顯示 502 Bad Gateway」
1. **原因**：ngrok 守護程序在跑，但 Streamlit 尚未就緒或被意外終止。
2. **診斷指令**（PowerShell）：
   ```powershell
   Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue
   ```
3. **解決方案**：
   - 查看 `data/streamlit_service.log` 末端報錯。
   - 確保 Streamlit 啟動參數包含 `--server.headless true` 且 `stdin=subprocess.DEVNULL`。
   - 在系統匣圖示點選「🔄 重新啟動服務」。

### 情況 B：使用者回報「ngrok 提示 The endpoint is already online」
1. **原因**：之前的 ngrok 進程異常殘留，佔用了免費方案唯一的 Dev Domain。
2. **解決方案**：
   - 執行 `taskkill /F /IM ngrok.exe` 清理殘留進程。
   - 重啟 `scripts/serve_line_bot.py`，該指令已內建自動清理 orphan ngrok 進程邏輯。

### 情況 C：LINE 機器人沒有回覆
1. **檢查 Webhook 服務與端口 8001**：
   ```powershell
   Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
   ```
2. **檢查 Cloudflare 通道與日誌**：
   - 查看 `data/bot_service.log`。
   - 若遇到 Cloudflare 429 / 1015 速率限制，通常等待 5 分鐘重試即可恢復。
3. **檢查 LINE Channel 狀態**：
   - 確認 `config/line_notifier.yaml` 的 `channel_access_token` 是否有效。
   - 確認 LINE 官方後台（manager.line.biz）之「回應模式」設為 **Bot**，且「自動回應訊息」為 **停用**。

### 情況 D：測試整體服務的一鍵檢查腳本
接手 Agent 可直接在專案根目錄執行此一鍵驗證指令：
```powershell
python -c "
import urllib.request, json
# 1. 檢查本機 Streamlit
try:
    code = urllib.request.urlopen('http://127.0.0.1:8501').getcode()
    print('✅ Streamlit 本地正常 (HTTP', code, ')')
except Exception as e:
    print('❌ Streamlit 本地異常:', e)

# 2. 檢查本機 LINE Webhook
try:
    code = urllib.request.urlopen('http://127.0.0.1:8001/').getcode()
    print('✅ LINE Webhook 本地正常 (HTTP', code, ')')
except Exception as e:
    print('❌ LINE Webhook 本地異常:', e)

# 3. 檢查運行時狀態檔
try:
    with open('data/line_bot_runtime.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print('✅ 運行狀態檔已加載，公網網址:', data.get('streamlit_url'))
except Exception as e:
    print('❌ 運行狀態檔異常:', e)
"
```

---
*本手冊由 Antigravity 核心工程團隊編纂，妥善保存於專案之 `docs/AGENT_HANDOFF_AND_LINE_BOT_MANUAL.md`，交接無縫、歷久彌新。*
