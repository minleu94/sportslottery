# 維運指南：研究流程、排程、備份與復原

本文件供開發與維護者使用，涵蓋 wheel 安裝、研究排程、備份、復原與版本發布。朋友使用安裝包請看 [朋友安裝指南](INSTALL_FOR_FRIENDS.md)。

本專案可直接從原始碼 checkout 執行，亦可透過安裝好的 wheel 執行。排程執行的研究流程（Research Pipeline）不涉及真實資金下注，所有資料皆寫入設定的獨立研究資料目錄。執行完成僅代表各階段順利跑完，不代表證明模型獲利或已驗證投注回報。

## 將 Wheel 安裝至獨立 Workspace

將 wheel 安裝至 Python 3.11 或 3.12 環境，並將執行時期環境落地至可寫入目錄中。升級版本時請保留該工作目錄與其 `data` 目錄；wheel 負責發布程式碼，工作目錄則存放可編輯的設定與研究紀錄。

```powershell
py -m venv C:\SportsLottery\venv
C:\SportsLottery\venv\Scripts\python.exe -m pip install .\dist\sportslottery-2.4.0-py3-none-any.whl
$env:SPORTSLOTTERY_WORKSPACE = 'C:\SportsLottery\workspace'
C:\SportsLottery\venv\Scripts\sportslottery.exe --workspace $env:SPORTSLOTTERY_WORKSPACE research-pipeline --dry-run
```

`--workspace` 參數優先於環境變數 `SPORTSLOTTERY_WORKSPACE`。啟動器會將打包的執行時期檔案複製至該目錄，並保留現有工作區設定，將套件內建預設值存放在 `config/defaults/`。在開始收集資料前，請先檢視 `config/research_pipeline.yaml` 並執行 dry-run：

```powershell
C:\SportsLottery\venv\Scripts\sportslottery.exe --workspace C:\SportsLottery\workspace research-pipeline --dry-run
C:\SportsLottery\venv\Scripts\sportslottery.exe --workspace C:\SportsLottery\workspace research-pipeline
```

在鎖定環境中，請明確傳入其 Python 執行檔路徑。排程輔助腳本支援 `-PythonPath`；若環境中有 `pythonw.exe`，建議優先指定以避免跳出終端機黑視窗；若只有 `python.exe` 亦可使用。若兩者並存於同一目錄，輔助腳本會以 `python.exe` 進行檢查並排定 `pythonw.exe`。

研究流程不需要任何外部 API 金鑰或憑證環境變數。wheel 啟動器支援 `SPORTSLOTTERY_WORKSPACE`；排程輔助腳本則會在 Windows 工作排程器中記錄絕對路徑的工作區、設定檔與資料目錄。可於 YAML 設定 `data_root` 或透過 `--data-root` 指定研究帳本存放位置，並請務必與正式生產資料目錄分開。

## Windows 工作排程器設定

請先檢查產生的排程計畫。以下指令僅驗證設定並輸出計畫，不會直接註冊排程：

```powershell
.\scripts\install_research_task.ps1 -DryRun `
  -WorkingDirectory C:\SportsLottery\workspace `
  -PythonPath C:\SportsLottery\venv\Scripts\pythonw.exe `
  -DataRoot C:\SportsLottery\research
```

在檢視計畫並確認該帳戶具備工作區讀取權與研究目錄寫入權後，排程註冊會使用當前使用者的互動式登入身分（Interactive Logon），不儲存明文密碼。互動式工作僅在該使用者登入期間執行；在使用者登出後不會作為背景服務運作。請勿僅憑排程已啟用就認定執行成功，請檢查排程執行結果與儲存的 pipeline 健康狀態紀錄。

若需無桌面登入的背景服務模式，可透過 Windows `SYSTEM` 服務帳號避免儲存憑證，此模式需要明確指定工作區路徑：

```powershell
.\scripts\install_research_task.ps1 -DryRun -RunAsSystem `
  -WorkingDirectory C:\SportsLottery\workspace `
  -PythonPath C:\SportsLottery\venv\Scripts\pythonw.exe `
  -DataRoot C:\SportsLottery\research
```

在正式註冊前，請務必確認所選的工作區、Python 執行時期與研究資料目錄皆允許 `SYSTEM` 帳號讀寫。使用者目錄下的 virtualenv、使用者私有設定、網路對應磁碟或使用者專屬 ACL 在該帳號下可能無法存取。該排程動作僅限於本機，不會取得已登入使用者的使用者目錄權限。僅在明確指定 `-RunAsSystem` 時才會變更主體；否則現有排程將維持當前使用者身分。

使用腳本的 `-Uninstall` 選項可移除具備專案標記的工作排程。請勿對已更名或由其他部署取代的工作排程執行解除安裝。

## 備份與復原

在變更工作區或資料前請先建立備份。請選擇原始程式碼 `data`、`core`、`scripts`、`config` 等備份範圍以外的目的目錄：

```powershell
python .\main.py backup --output D:\SportsLotteryBackups
```

指令會輸出帶有時間戳記的備份目錄路徑與檔案數量。備份會複製支援的執行時期目錄與 `data`，記錄 SHA-256 雜湊值，並在讀取時持有 pipeline lock。備份不包含 Python 本身、已安裝依賴套件、作業系統工作排程註冊或未聲明備份的外部檔案。

復原時只能指定全新且空的目標路徑；現有路徑會被拒絕以防止覆寫：

```powershell
python .\main.py restore `
  --backup D:\SportsLotteryBackups\20261015T120000Z_ab12cd34 `
  --destination D:\SportsLottery\recovered
```

復原程序會比對每個已儲存檔案的雜湊值並寫入憑據。在相容的 Python 環境中安裝相依套件後，請檢視復原後的 `config/research_pipeline.yaml`，並在恢復收集前對復原後的工作區執行 dry-run。請定期備份，並在工作磁碟之外至少保留一份獨立備份。

## 聯賽覆蓋狀態說明

- `available_third_party_verified_observed_slate`：表示已針對所列出的觀測賽事驗證第三方公開路徑與精確身分。這不代表具備完整的聯賽球隊名冊、保證未來的資料可用性或官方資料授權合約。
- `unsupported_source_unverified`：表示當前的來源路徑與身分範圍尚未經查驗；這不代表該賽事在所有地方都沒有比分或來源。健康狀態面板會針對特定賽事（如土耳其甲級聯賽或白俄羅斯超級聯賽）保留具體原因與查驗依據，使其保持可見且不被誤報為無比分。

## Windows 維運注意事項

- 請使用較短的備份目標路徑（例如 `D:\SLBackups` 或 repo 底下的 `backups` 目錄），避免深層路徑加長檔名超出 Windows 路徑長度上限。
- 失敗的備份作業會保留 `.incomplete` 暫存目錄；只有具備完整已驗證清單的完成目錄才是可用備份。
- 備份程序會先對 SQLite 資料庫與 JSONL 帳本拍攝快照並釋放鎖定，再複製公開來源檔案。Pipeline lock 在備份期間維持鎖定。備份期間請凍結原始碼與設定編輯；未透過共用鎖定的外部寫入者無法保證一致性。
- 復原指令一律要求全新的目標路徑，並在發布前檢查已聲明的清冊與檔案雜湊值。

## 發布安裝包

GitHub Actions 工作流程位於 `.github/workflows/build_releases.yml`。推送 `v*` 格式的 tag 會建立 Windows 安裝版、Windows 免安裝版與 macOS DMG，並附加到 GitHub Release。安裝包目前使用 `desktop_launcher.py` 啟動 Streamlit 桌面介面。

發布前先確認版本號、程式碼與工作流程；建立版本標籤後推送：

```powershell
git tag vX.Y.Z
git push origin vX.Y.Z
```

確認 GitHub Actions 成功並檢查 Release 附件後，再把 Releases 頁面提供給使用者。不要把尚未完成的 Actions artifact 當作正式版本。

Windows 本機打包可使用 `packaging/windows/build_windows.ps1 -Version X.Y.Z`。本機若未安裝 Inno Setup，腳本只會產生免安裝 ZIP；跨平台 Release 建置以 GitHub Actions 為準。
