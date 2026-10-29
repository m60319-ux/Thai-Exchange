from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import re

sources = {
  "cathay_main":"https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/",
  "cathay_accessibility":"https://accessibility.cathaybk.com.tw/exchange-rate-search.aspx",
  "taishin_realtime":"https://web.taishinbank.com.tw/TSB/personal/deposit/lookup/realtime/",
  "taishin_accessibility":"https://my.taishinbank.com.tw/AccWeb/AW2/AW02020004.jsp"
}
for k,uri in sources.items():
  try:
    resp=requests.get(uri,headers={"User-Agent":"Mozilla/5.0","Accept":"text/html,*/*"},timeout=(10,20),params={"_":int(datetime.now(timezone.utc).timestamp())})
    soup=BeautifulSoup(resp.content,"html.parser")
    content=soup.get_text(" ",strip=True)
    print("\nBANK PROBE:",k,"status",resp.status_code,"chars",len(content),"htmlbytes",len(resp.content))
    print("head:",repr(content[:800]))
    for word in ("資料時間","現鈔匯率","現鈔賣出","美元現鈔","匯率更新時間","更新日期","更新時間"):
      idx=content.find(word)
      if idx>=0:print(word,repr(content[max(0,idx-80):idx+230]))
    print("tables:",len(soup.select("table")),"rows:",len(soup.select("tr")),"select:")
    for row in soup.select("tr")[:8]:
      print("ROW",repr(row.get_text(" ",strip=True)[:210]))
    for phrase in ["美元USD","歐元EUR","日圓JPY","人民幣CNY","韓元KRW"]:
      tag=soup.find(string=re.compile(re.escape(phrase)))
      if tag and tag.parent:
        parent=tag.parent
        print("MARKUP",phrase,str(parent.parent)[:580].replace("\n"," "))
  except Exception as ex:
    print("\nBANK PROBE FAILED",k,type(ex).__name__,str(ex)[:200])
