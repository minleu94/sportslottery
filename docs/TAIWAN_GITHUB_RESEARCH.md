# 台灣運彩與體育博弈開源專案調研報告 (TAIWAN_GITHUB_RESEARCH.md)

**調研日期**：2026-09-18  
**調研範圍**：GitHub 上與「台灣運彩」、「玩運彩 (Playsport)」、「運動彩券賠率爬蟲」相關之開源專案。

---

## 1. 台灣相關開源專案矩陣

| Repo | 功能說明 | 最近更新 | Stars | License | 可重用價值評估 | 採用狀態與定位 |
| :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **[CharlieAlex/Sports-Betting-Freerider](https://github.com/CharlieAlex/Sports-Betting-Freerider)** | 爬取玩運彩主推榜預測、統計勝率熱度、串接 Line Bot 與 Streamlit | 2024 | 12 | MIT | **極高**：深入示範了 Playsport 主推榜與預測比例之爬取邏輯與資料結構。 | **核心參考**：用於本專案之 Playsport 盤口與專家榜爬蟲設計。 |
| **[YuanData/MLB_python-Crawler_and_R-predictive-analysis](https://github.com/YuanData/MLB_python-Crawler_and_R-predictive-analysis)** | 爬取台灣運彩 MLB 賠率，結合 MongoDB 儲存並用 R 語言做預測 | 2023 | 5 | Unlicense | **中高**：提供台灣運彩讓分、大小分盤口欄位之正規化對齊思路。 | **架構參考**：用於台彩盤口 Normalization（讓分/不讓分/大小）。 |
| **[asadman1523/sportlotterycomtw_report](https://github.com/asadman1523/sportlotterycomtw_report)** | Chrome 擴充套件，在運彩官網「我的投注」頁面攔截注單損益並匯出 CSV | 2024 | 8 | MIT | **中等**：提供官方注單資料欄位結構與 ROI 計算標準。 | **風控參考**：用於注單損益與流水帳結構借鑑。 |
| **[stu01509/TaiwanLotteryCrawler](https://github.com/stu01509/TaiwanLotteryCrawler)** | 台灣彩券（樂透/威力彩/539）歷史開獎爬蟲 | 2024 | 85 | MIT | **中等**：穩定爬蟲架構與防封重試機制設計。 | **架構參考**：用於快取與異常退避重試邏輯。 |
| **[ywchiu/largitdata](https://github.com/ywchiu/largitdata)** | 大數學堂運彩賠率爬蟲實戰教學教材 | 2022 | 150+ | MIT | **技術參考**：展示如何逆向 Network JSON 請求以繞過靜態 HTML 阻擋。 | **技術參考**：用於解析 Playsport 頁面中 Vue `vueData` 嵌入式 JSON。 |
| **WIN88運彩下注系統 (學生專題群)** | 模擬運彩下注平台、會員資金管理與派彩結算 | 2023 | 3 | None | **低**：教學性質，無即時爬蟲能力。 | **未採用**：代碼品質與成熟度不足。 |

---

## 2. 官方網站 (`sportslottery.com.tw`) 現況調研

- **官方 API 現狀**：台灣運彩官方（威剛，運彩 3.0）**未提供任何公開 API**。
- **反爬機制實測**：使用標準 Python `requests` 對 `https://www.sportslottery.com.tw` 發送請求，回傳 **HTTP 403 Forbidden**（受 Cloudflare / WAF 嚴格阻擋與驗證碼防護）。
- **開源界通用解法**：台灣運動博弈社群普遍以 **「玩運彩 (Playsport.cc)」** 作為台彩即時盤口之鏡像來源。Playsport 會即時同步台灣運彩之「運彩盤（讓分、不讓分、大小分、客主和）」與威剛官方賽事編號，且伺服器對爬蟲較具容忍度，因此被選定為本系統之 **Layer A (台灣運彩核心投注盤口來源)**。

---

## 3. 本專案對台灣開源生態的繼承與創新

1. **繼承**：
   - 吸收 `Sports-Betting-Freerider` 爬取玩運彩專家主推榜與大眾投票數量的經驗。
   - 吸收 `YuanData` 對台彩讓分（客 -1.5, 主 +1.5）與大小分門檻的解析規則。
   - 吸收 `largitdata` 直接擷取 `vueData` 結構化資料的快速解析技巧（$O(N)$ 單次遍歷）。
2. **創新與超越**：
   - 建立 **Layer A (台彩盤口) $\to$ Layer B (國內外模型評估) $\to$ Layer C (國際賽程雷達)** 之嚴密架構。
   - 徹底杜絕將「大眾投票」偽裝成「大神看好」的業界通病，將 Expert 與 Crowd 嚴格分離。
   - 串接國際開源運動模型（`penaltyblog`、`pybaseball`）直接評估台灣運彩具體選項。
   - 獨創 **每週 NT$ 200 錢包 + 獲利保留池 (Prize Pool) 自動滾存機制**，提供真正嚴格的風控鎖定。
