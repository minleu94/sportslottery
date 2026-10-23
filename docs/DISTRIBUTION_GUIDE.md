# 🐕 台灣運彩「瘋狗流」決策系統 —— 跨平台分發與安裝指南

本手冊說明如何將本系統打包為**免安裝 Python、免終端機設定**的獨立安裝包，並提供給 Windows 11 與 macOS 朋友使用的完整步驟。

---

## 快速導覽：朋友應該去哪裡下載？

在您將專案設定好 GitHub Actions 後，您可以直接把 GitHub 的 **Releases 下載頁面** 傳給朋友：
> 下載網址範例：`https://github.com/<您的用戶名>/sportslottery/releases`

朋友進入頁面後，根據他的電腦系統點選對應檔案下載：

| 朋友的電腦系統 | 點擊下載的檔案 | 檔案類型 | 安裝方式 |
| :--- | :--- | :--- | :--- |
| **Windows 11 (PC)** | `Sportslottery_Win11_Setup_v2.1.0.exe` | 一鍵安裝精靈 | 雙擊安裝，自動建立桌面捷徑 |
| **Windows 11 (免安裝)** | `Sportslottery_Win11_Portable_v2.1.0.zip` | 綠色便攜包 | 解壓縮後雙擊 `Sportslottery.exe` 即開即用 |
| **macOS (蘋果電腦)** | `Sportslottery_macOS_v2.1.0.dmg` | Mac 映像檔 | 雙擊掛載後，拖曳至「應用程式」即可 |

---

## 一、 朋友使用指南（給非技術朋友看的安裝說明）

### 1. Windows 11 安裝步驟（最簡單）
1. 下載 `Sportslottery_Win11_Setup_v2.1.0.exe`。
2. 雙擊執行安裝程式。
   - *（若 Windows Defender 提示「未知發行者」，點擊「其他資訊」->「仍要執行」即可）*。
3. 按照精靈提示點擊「下一步」，程式會自動安裝至電腦中，並在**桌面產生「台灣運彩瘋狗流決策系統」圖示**。
4. 安裝完成後，直接在桌面雙擊圖示：
   - 黑色系統視窗將會啟動引擎。
   - **約 2~3 秒內會自動在瀏覽器彈出決策台（http://localhost:8501）**。
5. **關閉方式**：直接關閉黑色系統視窗或瀏覽器分頁即可。

---

### 2. macOS 安裝步驟（蘋果電腦）
1. 下載 `Sportslottery_macOS_v2.1.0.dmg`。
2. 雙擊開啟 DMG 檔案。
3. 將畫面中的 **Sportslottery 圖示** 拖入 **Applications（應用程式）** 資料夾。
4. 進入 Launchpad（啟動台）或應用程式資料夾，點擊 **Sportslottery**。
   - *（若 macOS 彈出安全性提示「無法驗證開發者」，請至「系統設定」->「隱私權與安全性」-> 點擊「強制打開」或右鍵選擇「打開」即可）*。
5. 程式啟動後，會自動在 Safari 或預設瀏覽器中開啟決策台。

---

## 二、 開發者指南：如何發布新版本給朋友？

### 途徑 A：透過 GitHub 雲端全自動打包發布（最推薦）
本專案已配置好 `.github/workflows/build_releases.yml` 雲端自動構建工作流：
1. 您在本地完成代碼開發或更新後，提交並推送到 GitHub：
   ```bash
   git add .
   git commit -m "發布 v2.1.0 雙平台獨立安裝版本"
   git push origin main
   ```
2. 建立並推送版本標籤（Tag）：
   ```bash
   git tag v2.1.0
   git push origin v2.1.0
   ```
3. GitHub 雲端虛擬機會**同時啟動 Windows 11 機器與 macOS 機器**，自動執行打包並在 5~8 分鐘內將 `Setup.exe`、`Portable.zip` 與 `macOS.dmg` 附件自動掛載在 GitHub Releases 頁面！
4. 您只要將 Release 頁面連結複製給朋友即可。

---

### 途徑 B：在您目前的 Windows 11 本機直接打包
若您目前不想使用 GitHub，想直接在您本機產生可傳給 Windows 朋友的檔案：
1. 開啟 PowerShell，切換至專案根目錄。
2. 執行 Windows 一鍵打包腳本：
   ```powershell
   .\packaging\windows\build_windows.ps1
   ```
3. 執行完成後，打包產物會自動存放在專案下的 `dist/installer/`：
   - `dist/installer/Sportslottery_Win11_Portable_v2.1.0.zip`
4. 您可以直接將這個 `.zip` 壓縮檔透過 LINE、Google 雲端硬碟或隨身碟傳給朋友！
   - 朋友解壓縮後，點進資料夾雙擊 `Sportslottery.exe` 即可開箱即用！

---

## 三、 資料安全與升級相容機制

1. **原作者電腦（維持現有配置）**：
   - 系統依舊優先讀取您的 `F:\Min\Python\Project\SportsLottery_Data` 磁碟與既有資料庫，所有設定與排程完全不受影響。
2. **朋友的全新電腦（自動建立專屬資料庫）**：
   - 當系統偵測到朋友電腦沒有 F 槽時，會自動在朋友的電腦建立專屬資料夾：
     - **Windows 11**：`C:\Users\<用戶名>\AppData\Local\SportsLottery\data\`
     - **macOS**：`/Users/<用戶名>/Library/Application Support/SportsLottery/data/`
   - 即使朋友未來安裝新版本軟體，他的個人投注紀錄與 SQLite 資料庫也不會被覆蓋或清空！
