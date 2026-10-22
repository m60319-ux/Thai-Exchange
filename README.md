# Thai-Exchange｜泰銖換匯決策儀表板

比較將新台幣兌換泰銖的六種方式：直接使用台幣，或先在臺灣銀行以**現鈔賣出價**兌換美元、歐元、日圓、韓元、人民幣，再以 **Grand SuperRich 現鈔買入價**兌換泰銖。

## 使用方式

- 直接開啟網頁的 `index.html`。
- 可修改投入本金、額外手續費及兩家換匯牌告，立即重新排名。
- 歷史趨勢圖有 7 天、30 天、3 個月、6 個月及 1 年選擇，需網路連線。
- **現鈔價格不是自動更新**：初始價格是 **2026-10-19** 的參考快照，請使用時核對 [台灣銀行](https://rate.bot.com.tw/xrt/) 與 [Grand SuperRich](https://www.grandsuperrich.com/) 官方牌告。
- **歷史趨勢是市場參考價**，來自 Frankfurter，並不是 Grand SuperRich 歷史現鈔買入價格。

## GitHub Pages 發布

在此專案的 **Settings → Pages → Build and deployment**：
選擇 **Deploy from a branch**，分支選 **main**、目錄選 **/(root)**，按下 Save。

發布後，預設網站地址：

https://m60319-ux.github.io/Thai-Exchange/

此網頁為純靜態 HTML，無需後端。實際收到的現鈔金額可能因面額、手續費、門市牌告或庫存而有所不同。
