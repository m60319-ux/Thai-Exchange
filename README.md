# Thai-Exchange｜泰銖換匯決策儀表板

[開啟換匯網站](https://m60319-ux.github.io/Thai-Exchange/)

**v2.3｜維持既有前端版型，移除臺灣銀行資料來源。**

## 換匯路線與官方銀行順序

比較直接帶 TWD 現鈔到 Grand SuperRich 兌換泰銖，以及先在臺灣購買 USD、EUR、JPY、KRW、CNY 現鈔後，再到 Grand SuperRich 兌換泰銖。

購買外幣時只採用以下**銀行官網現鈔賣出價**，**依幣別**選擇第一個可用且時間有效的報價：

1. **國泰世華銀行（優先）**：[官方外幣匯率](https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/) — 使用「現鈔匯率」的**銀行賣出**欄，不使用即期或數位通路優惠匯率。
2. **台新銀行（備援）**：[官方現鈔賣出頁](https://my.taishinbank.com.tw/AccWeb/AW2/AW02020004.jsp) — 國泰未提供或無法取得特定幣別時才採用。

泰銖端使用 [Grand SuperRich 官網](https://www.grandsuperrich.com/rate.php) 對應面額的**現鈔買入價**。

每個幣別的來源銀行及掛牌時間都存於 `rates.json` 的 `official.bank.currency_sources`，並在網站上顯示。若兩家銀行均沒有特定幣別的現鈔賣出牌告（目前 KRW 常見此狀況），顯示**不提供**，不會使用即期匯率、其他銀行或估算值替代。

## 官方與參考資料區分

- **官方試算**：銀行端使用國泰世華／台新官網現鈔賣出價，泰銖端使用 Grand SuperRich 官網現鈔買入價。
- **參考試算**：銀行端仍使用國泰世華／台新**官方**現鈔賣出價，僅泰銖端改用 [RuamThai](https://exchange.ruamthai.com/en/shop/grand-superrich) 第三方轉載的 Grand SuperRich **參考買入價**。這不是完整官方報價。
- **手動試算**：使用者自行修改匯率，不代表當日現鈔報價。

畫面結構、金額切換、六種幣別設定、歷史市場匯率圖表、複製與 CSV 匯出均保留。未有現鈔報價的外幣不列入可得泰銖排名。

Grand SuperRich 選用紙鈔面額：USD 100、EUR 100–500、JPY 5,000–10,000、CNY 100、KRW 排除 1,000 元小鈔、TWD 一般台幣現鈔。若對應面額報價無法辨識，該資料來源會失敗，不會任意拿其他級距冒充。

## GitHub Actions 與發布

工作流程：[Refresh Cathay-Taishin and Grand SuperRich cash rates](https://github.com/m60319-ux/Thai-Exchange/actions/workflows/update-rates.yml)。

排程原則上每天泰國時間 08:17–20:17 每小時檢查（GitHub 排程可能延遲）。輸出 `rates.json`（schema v2）的主要欄位：

- `official.cathay`、`official.taishin`：兩家銀行官網的擷取狀態及現鈔賣出價。
- `official.bank`：按照優先順序合成的可用現鈔價，附每個幣別來源、時間及不支援幣別。
- `official.grand_superrich`：指定面額的官方泰銖現鈔買入價。
- `reference.bank`：同一組**官方**銀行現鈔賣出價（不額外從其他網站抓銀行匯率）。
- `reference.grand_superrich`：RuamThai 第三方轉載的參考現鈔買入價。

**執行成功不保證所有報價都成功取得**：請以各筆 `status`、`quoted_at` 和頁面上的來源提示為準。最後成交價格以分行及 Grand SuperRich 門市當日牌告為準。

每次變更會執行 Python 解析器離線測試、JavaScript 語法檢查、模擬瀏覽器的官方／參考／手動試算測試，並測試依幣別改用台新及不提供韓元時的畫面狀態。

本站由 GitHub Pages 的 `main` 分支根目錄 `index.html` 提供。
