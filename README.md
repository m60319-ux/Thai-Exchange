# Thai-Exchange｜泰銖換匯決策儀表板

[打開換匯網頁](https://m60319-ux.github.io/Thai-Exchange/)

比較六種路線：直接以台幣現鈔兌泰銖；或先向台灣銀行以 **現鈔賣出價** 購買 USD、EUR、JPY、KRW、CNY，再到 Grand SuperRich 以指定面額的 **現鈔買入價** 兌泰銖。

## 官方資料和第三方鏡像嚴格分離（v2）

網站由 GitHub Actions 定時檢查四個來源，結果分別存到 [rates.json](rates.json)：

| 分組 | 來源 | 用途 |
| --- | --- | --- |
| 官方 / 台灣銀行 | https://rate.bot.com.tw/xrt | 現鈔賣出（cash selling），**不是即期賣出** |
| 官方 / Grand SuperRich | https://www.grandsuperrich.com/rate.php | 嚴格依指定紙鈔面額的現鈔買入 |
| 第三方參考 / 台銀轉載 | https://raw.githubusercontent.com/haotool/app/data/public/rates/latest.json | **只在下方參考區顯示** |
| 第三方參考 / Grand SuperRich 轉載 | https://exchange.ruamthai.com/en/shop/grand-superrich | **只在下方參考區顯示** |

**重要：絕對不會把第三方鏡像升格為「官方牌告」。** 官方只要有一個來源無法直接取得、缺少價格或過期，上方的「官方換匯排名」就暫停，顯示「官方取得失敗」。第三方轉載在頁面下方有獨立來源時間、參考排名和警語。

Grand SuperRich 指定紙鈔面額：
- USD 100
- EUR 500–100
- JPY 10,000–5,000
- KRW 一般大面額，**排除 1,000 韓元小鈔**
- CNY 100
- TWD 一般台幣現鈔

如果頁面沒有這個確切級距，程式會標為失敗，**不會取其他級距的最高買入價冒充**。

## 操作

1. 打開網站：先看「官方網站牌告狀態」。
2. 兩家官方來源均正常時，主排名使用官方資料。
3. 官方來源失敗時，可在下方查看「第三方牌告轉載｜僅供參考」，它不會被納入官方排名。
4. 只有**手動啟用「手動輸入試算」**才能修改牌告；此模式明確標為非官方自動報價。
5. 市場歷史匯率曲線仍可選 7 天、30 天、3 個月、6 個月、1 年；曲線不是 SuperRich 現鈔買入價歷史。

**請勿誤判自動化工作成功：** GitHub Actions 執行成功只代表四個來源都已完成檢查、寫入結果，不代表官方擷取成功。必須查看 rates.json 的 \`official.bot.status\` 和 \`official.grand_superrich.status\` 是否同為 \`ok\`，網站才會顯示官方排名。

RuamThai 的頁面時間是第三方網站抓取時間的推估值，並不等於 Grand SuperRich 官方掛牌時間；頁面會清楚註明。程式不會用市場中間價補足現鈔匯率。

## 更新排程

[GitHub Actions](https://github.com/m60319-ux/Thai-Exchange/actions/workflows/update-rates.yml) 採 GitHub UTC cron 排程，原則上每天泰國時間 08:17～20:17 每小時檢查（GitHub 可能延誤或略過部分排程）。也可以按 **Run workflow** 手動重新檢查。

程式入口：\`scripts/update_rates.py\`。每次儲存的 schema v2 包含：
- \`checked_at\`：完成檢查的 UTC 時間。
- \`official.bot\` / \`official.grand_superrich\`：**只有官網直接讀取才會是 ok**。
- \`reference.bot\` / \`reference.grand_superrich\`：獨立鏡像參考資料。
- 錯誤時的 \`status: failed\`、\`error\`，以及不作為目前價格的 \`last_successful\` 歷史存檔（若有）。

GitHub Pages 使用 \`main\` 分支根目錄的 \`index.html\`。使用前務必核對交易時間、店家面額與門市臨櫃價格。
