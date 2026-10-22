# Thai-Exchange｜泰銖換匯決策儀表板

比較將新台幣兌換泰銖的六種方式：直接使用台幣，或先在臺灣銀行以**現鈔賣出價**兌換美元、歐元、日圓、韓元、人民幣，再以 **Grand SuperRich 現鈔買入價**兌換泰銖。

## 使用方式

- 直接開啟網頁的 `index.html`。
- 可修改投入本金、額外手續費及兩家換匯牌告，立即重新排名。
- 歷史趨勢圖有 7 天、30 天、3 個月、6 個月及 1 年選擇，需網路連線。
- **自動更新機制**：GitHub Actions 在泰國時間約 08:17～20:17 每小時排程查詢一次 [台灣銀行](https://rate.bot.com.tw/xrt/) 現鈔賣出價及 [Grand SuperRich](https://www.grandsuperrich.com/rate.php) 現鈔買入價。GitHub 排程可能延遲；這不是逐秒即時報價。
- 兩家來源的報價時間與數值都經程式檢查才會發布至 `rates.json`。若官方直接讀取被防護系統擋下，程式會嘗試以下標明出處的轉載鏡像：台銀 [HaoRate 資料](https://haotool.org/ratewise/open-data/)，Grand SuperRich [RuamThai 換匯彙整](https://exchange.ruamthai.com/en/shop/grand-superrich)。鏡像屬第三方資料，**不是官方直接驗證的即時報價**；網站會明確揭露來源與時間。任何擷取失敗、欄位缺漏或報價過期時，都不更新檔案；網站會顯示過期／同步失敗警示。
- **初始備援匯率**：2026-10-19 的歷史牌告快照；只有在讀取 `rates.json` 成功且通過驗證時，網頁才以自動牌告覆蓋它。
- **歷史趨勢是市場參考價**，來自 Frankfurter，並不是 Grand SuperRich 歷史現鈔買入價格。

## 自動同步狀態與手動觸發

在 [GitHub Actions](https://github.com/m60319-ux/Thai-Exchange/actions/workflows/update-rates.yml) 查看每次執行是否成功；可選 **Run workflow** 手動重新嘗試。程式位於 `scripts/update_rates.py`，工作流程位於 `.github/workflows/update-rates.yml`。

**注意：若 Actions 因官方網站反爬蟲、資料格式變更或帳號權限無法完成，則不代表自動更新可用。** 網站會繼續顯示舊資料並標註警告，請以實際成功執行及 `rates.json` 的來源時間為準。

## GitHub Pages 發布

在此專案的 **Settings → Pages → Build and deployment**：
選擇 **Deploy from a branch**，分支選 **main**、目錄選 **/(root)**，按下 Save。

發布後，預設網站地址：

https://m60319-ux.github.io/Thai-Exchange/

此網頁為純靜態 HTML，無需後端。實際收到的現鈔金額可能因面額、手續費、門市牌告或庫存而有所不同。
