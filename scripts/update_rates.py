#!/usr/bin/env python3
"""Separate OFFICIAL cash quotations from THIRD-PARTY reference quotations.

Never promote a mirrored quote to official. Missing official quotes are failures,
not permission to silently substitute estimated or market rates.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

CATHAY_URL = "https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/"
TAISHIN_URL = "https://my.taishinbank.com.tw/AccWeb/AW2/AW02020004.jsp"
GRAND_URL = "https://www.grandsuperrich.com/rate.php"
GRAND_MIRROR_URL = "https://exchange.ruamthai.com/en/shop/grand-superrich"
OUT = Path(__file__).resolve().parents[1] / "rates.json"
TW = ZoneInfo("Asia/Taipei")
TH = ZoneInfo("Asia/Bangkok")
CURRENCIES = ("TWD", "USD", "EUR", "JPY", "KRW", "CNY")
BANK_CURRENCIES = CURRENCIES[1:]
BOUNDS = {
    "TWD": (.6, 1.5), "USD": (20, 50), "EUR": (25, 60),
    "JPY": (.12, .4), "KRW": (.01, .06), "CNY": (3, 8)
}
# Exact intended cash banknote tier, *not* an arbitrary maximum across all rows.
DENOMINATIONS = {
    "TWD": "TWD（不限面額）",
    "USD": "USD 100",
    "EUR": "EUR 500-100",
    "JPY": "JPY 10000-5000",
    "KRW": "KRW（非 KRW 1000 小鈔）",
    "CNY": "CNY 100"
}


def request_text(url):
    response = requests.get(
        url,
        timeout=(12, 25),
        headers={"User-Agent": "Mozilla/5.0 (Thai-Exchange/2.0; source-attributed quotations)",
                 "Accept": "text/html,text/csv,application/json,*/*",
                 "Cache-Control": "no-cache"},
        params={"_": int(datetime.now(timezone.utc).timestamp())}
    )
    response.raise_for_status()
    response.encoding = "utf-8-sig"
    html = response.text.strip()
    if not html or "Challenge Validation" in html[:4000]:
        raise ValueError("網站回傳防護驗證頁，而非匯率牌告")
    return html


def price(code, value):
    val = float(value)
    low, high = BOUNDS[code]
    if not low <= val <= high:
        raise ValueError(f"{code} 報價超出合理範圍: {val}")
    return val


def assert_fresh(dt, label, hours=120):
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    if age < -timedelta(hours=2) or age > timedelta(hours=hours):
        raise ValueError(f"{label} 牌告時間不合理或已過期: {dt.isoformat()}")


def parse_grand_timestamp(html):
    txt = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(
        r"Last\s+updated\s+exchange\s+rate\s*[:：]\s*"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})\s*[-–]\s*(\d{1,2}:\d{2}:\d{2})",
        txt, re.I
    )
    if m:
        when = re.sub(r"\s+", " ", m.group(1)).replace(",", "")
        dt = datetime.strptime(when+" "+m.group(2), "%B %d %Y %H:%M:%S")
        return dt.replace(tzinfo=TH)
    m = re.search(r"Last\s+Update\s*(\d{1,2}):(\d{2}):(\d{2})\s+(\d{1,2})/([A-Za-z]+)/(\d{4})",
                  txt, re.I)
    if m:
        h, minute, second, d, mon, y = m.groups()
        dt = datetime.strptime(f"{d}/{mon}/{y} {h}:{minute}:{second}", "%d/%b/%Y %H:%M:%S")
        return dt.replace(tzinfo=TH)
    raise ValueError("Grand SuperRich 官方頁面缺少可驗證的牌告時間")


def banknote_match(code, label):
    # Official rows use "USD 100"; mirror rows use "USD US Dollar 100".
    # Inspect the denomination numbers after the ISO code, ignoring currency names.
    m = re.search(r"\b" + re.escape(code) + r"\b(.*)", label.upper())
    if not m:
        return False
    tail = m.group(1)
    nums = re.findall(r"\b\d+\b", tail)
    if code == "USD":
        return nums == ["100"]
    if code == "EUR":
        return nums == ["500", "100"]
    if code == "JPY":
        return nums == ["10000", "5000"]
    if code == "CNY":
        return nums == ["100"]
    if code == "KRW":
        return "1000" not in nums
    return not nums


def parse_grand_table(html):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    # Grand SuperRich migrated to gsr-rate-row DIVs (October 2026).
    # Read the cash BUY cell, not the SELL cell or a different banknote tier.
    for row in soup.select(".gsr-rate-row"):
        currency = row.select_one(".gsr-rate-currency")
        buy = row.select_one(".gsr-rate-buy")
        sell = row.select_one(".gsr-rate-sell")
        if currency and buy and sell:
            candidates.append((currency.get_text(" ", strip=True),
                               buy.get_text(" ", strip=True),
                               sell.get_text(" ", strip=True)))
    # Third-party mirror uses a normal TABLE (or older official formats).
    for tr in soup.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        label = " ".join(cell.get_text(" ", strip=True) for cell in cells[:-2])
        candidates.append((label, cells[-2].get_text(" ", strip=True),
                            cells[-1].get_text(" ", strip=True)))
    selections = {}
    labels = {}
    for label, buy_text, sell_text in candidates:
        matched = re.search(r"\b(TWD|USD|EUR|JPY|KRW|CNY)\b", label, re.I)
        if not matched:
            continue
        code = matched.group(1).upper()
        if not banknote_match(code, label):
            continue
        buy_text = buy_text.replace(",", "")
        sell_text = sell_text.replace(",", "")
        if not re.fullmatch(r"\d+(?:\.\d+)?", buy_text) or not re.fullmatch(r"\d+(?:\.\d+)?", sell_text):
            continue
        buying = price(code, buy_text)
        selling = float(sell_text)
        if selling < buying:
            raise ValueError(f"Grand SuperRich {code}: 買入大於賣出")
        if code in selections and selections[code] != buying:
            raise ValueError(f"Grand SuperRich {code}: 同面額有衝突報價")
        selections[code] = buying
        labels[code] = DENOMINATIONS[code]
    if set(selections) != set(CURRENCIES):
        raise ValueError("Grand SuperRich 缺少指定面額牌告：" +
                         ",".join(sorted(set(CURRENCIES) - set(selections))))
    return selections, labels


def grand_mirror(raw):
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    m = re.search(r"\b(\d{1,4})\s*(m|h|d|minutes?|hours?|days?)\s+ago\b",
                  text[:1500], re.I)
    if not m:
        raise ValueError("Grand SuperRich 鏡像沒有最近取得時間")
    n = int(m.group(1))
    unit = m.group(2).lower()
    age_minutes = n * (1440 if unit.startswith("d") else 60 if unit.startswith("h") else 1)
    if age_minutes > 180:
        raise ValueError("Grand SuperRich 鏡像超過 3 小時未取得資料")
    estimate = datetime.now(TH) - timedelta(minutes=age_minutes)
    rates, labels = parse_grand_table(raw)
    return estimate, rates, labels


def ok_record(url, timestamp, kind, **fields):
    return {"status": "ok", "source": url, "retrieval": kind,
            "quoted_at": timestamp.isoformat(), **fields}


def failure_record(url, err):
    return {"status": "failed", "source": url, "error": str(err)[:230]}


def attempt(func, url, name):
    try:
        data = func()
        print(name, "OK:", data.get("quoted_at", ""))
        return data
    except Exception as ex:
        print(name, "FAILED:", str(ex)[:230], file=sys.stderr)
        return failure_record(url, ex)


def parse_cathay_cash_rates(html):
    """Cathay official currency billboard: use ONLY 現鈔匯率 Bank SELL.

    Some currencies (notably KRW) do not have a published CASH tier.
    Missing cash instruments are recorded as unavailable, never filled with spot.
    """
    soup = BeautifulSoup(html, "html.parser")
    body = soup.get_text(" ", strip=True)
    stamp = re.search(
        r"資料時間\s*(?:Board\s*time)?\s*[:：]?\s*"
        r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*"
        r"(\d{1,2}):(\d{2}):(\d{2})", body, re.I
    )
    if not stamp:
        raise ValueError("國泰世華官網缺少資料時間")
    quoted_at = datetime(*map(int, stamp.groups()), tzinfo=TW)
    assert_fresh(quoted_at, "國泰世華官方")
    # The billboard has dropdown currency options BEFORE the price panels;
    # only parse the text AFTER the published board timestamp.
    quoted_section = body[stamp.end():]
    headings = list(re.finditer(
        r"(?:美元|歐元|日圓|人民幣)\s*(USD|EUR|JPY|CNY)\s*歷史走勢",
        quoted_section, re.I
    ))
    if len(headings) < 3:
        raise ValueError("國泰世華官網找不到實際幣別牌告區塊")
    rates = {}
    for i, header in enumerate(headings):
        code = header.group(1).upper()
        rest = quoted_section[header.end():headings[i+1].start() if i+1<len(headings) else None]
        # e.g. 現鈔匯率 32.1300 32.7300
        m = re.search(r"現鈔匯率\s+(\d+(?:\.\d+)?|--|-)\s+(\d+(?:\.\d+)?|--|-)", rest)
        if m and re.fullmatch(r"\d+(?:\.\d+)?", m.group(2)):
            rates[code] = price(code, m.group(2))
    if not rates:
        raise ValueError("國泰世華找不到任何有效現鈔賣出價")
    return quoted_at, rates


def parse_taishin_cash_rates(html):
    """Taishin official accessibility site: one table for CASH SELL only."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.get_text(" ", strip=True)
    if "現鈔賣出" not in body or "現鈔賣匯" not in body:
        raise ValueError("台新官網不是現鈔賣出價頁面")
    stamp = re.search(
        r"更新日期\s*[:：]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日"
        r"\s*(AM|PM)\s*(\d{1,2})時(\d{1,2})分", body, re.I
    )
    if not stamp:
        raise ValueError("台新官網缺少現鈔牌告更新時間")
    y, mo, day, meridian, hh, minute = stamp.groups()
    hour = (int(hh) % 12) + (12 if meridian.upper()=="PM" else 0)
    quoted_at = datetime(int(y),int(mo),int(day),hour,int(minute),tzinfo=TW)
    assert_fresh(quoted_at, "台新銀行官方")
    rates = {}
    for tr in soup.select("tr"):
        cells = tr.find_all("td",recursive=False)
        if len(cells)<2:continue
        code_match = re.search(r"(USD|EUR|JPY|KRW|CNY)",cells[0].get_text(" ",strip=True),re.I)
        if not code_match:continue
        code = code_match.group(1).upper()
        val = cells[1].get_text(" ",strip=True)
        if re.fullmatch(r"\d+(?:\.\d+)?",val):
            rates[code]=price(code,val)
        # '-' is deliberately NOT a cash-selling quotation.
    if not rates:
        raise ValueError("台新銀行找不到有效現鈔賣出價")
    return quoted_at,rates


def official_cathay():
    when,rates=parse_cathay_cash_rates(request_text(CATHAY_URL))
    return ok_record(CATHAY_URL,when,"official_direct",
                     bank_name="國泰世華銀行",cash_sell=rates,
                     unsupported=[ccy for ccy in BANK_CURRENCIES if ccy not in rates])


def official_taishin():
    # Read the official accessibility CASH-SELL table, not the realtime spot rows.
    import requests
    resp=requests.get(TAISHIN_URL,timeout=(12,25),
                      headers={"User-Agent":"Mozilla/5.0",
                               "Accept":"text/html,*/*",
                               "Cache-Control":"no-cache"},
                      params={"_":int(datetime.now(timezone.utc).timestamp())})
    resp.raise_for_status()
    # Detect charset from the document, including legacy Big5 pages.
    soup=BeautifulSoup(resp.content,"html.parser")
    when,rates=parse_taishin_cash_rates(str(soup))
    return ok_record(TAISHIN_URL,when,"official_direct",
                     bank_name="台新銀行",cash_sell=rates,
                     unsupported=[ccy for ccy in BANK_CURRENCIES if ccy not in rates])


def choose_official_cash_bank(candidates):
    """Select cash rates in priority order, *per currency*, with full provenance.

    No invented cash quotes for unsupported currencies; no market/spot fallback.
    """
    priority=[("cathay","國泰世華銀行"),("taishin","台新銀行")]
    selected={}
    provenance={}
    for code in BANK_CURRENCIES:
        for bank,label in priority:
            rec=candidates[bank]
            if rec.get("status")!="ok":continue
            v=rec.get("cash_sell",{}).get(code)
            if v is None:continue
            val=price(code,v)
            selected[code]=val
            provenance[code]={"bank":bank,"bank_name":label,
                "source":rec["source"],"quoted_at":rec["quoted_at"]}
            break
    if not selected:
        return failure_record(CATHAY_URL,
            "國泰世華與台新銀行均無可用現鈔賣出牌告")
    timestamps=[datetime.fromisoformat(rec["quoted_at"]) for rec in provenance.values()]
    return ok_record(provenance[next(iter(selected))]["source"],min(timestamps),
                     "official_cascade",
                     bank_name="國泰世華 → 台新（依幣別回退）",
                     cash_sell=selected,currency_sources=provenance,
                     unsupported=[code for code in BANK_CURRENCIES if code not in selected])


def official_grand():
    # Two pages on the Grand SuperRich official domain; neither is a mirror.
    errors = []
    for url in (GRAND_URL, "https://www.grandsuperrich.com/index.php?languageID=49"):
        try:
            html = request_text(url)
            date = parse_grand_timestamp(html)
            try:
                rates, labels = parse_grand_table(html)
            except ValueError:
                soup = BeautifulSoup(html, "html.parser")
                sample = [tr.get_text(" ", strip=True)[:145]
                          for tr in soup.select("tr")[:6]]
                print("Grand official HTML diagnostics:",
                      "rows=", len(soup.select("tr")),
                      "examples=", repr(sample),
                      "visible_text=", repr(soup.get_text(" ", strip=True)[:450]),
                      "USD_excerpt=", repr(html[max(0,html.find("USD")-120):html.find("USD")+230]) if "USD" in html else "(no USD token)",
                      file=sys.stderr)
                raise
            assert_fresh(date, "Grand SuperRich 官方")
            return ok_record(url, date, "official_direct",
                             cash_buy=rates, denomination_labels=labels)
        except Exception as ex:
            errors.append(str(ex)[:140])
    raise ValueError("；".join(errors))


def reference_grand():
    date, rates, labels = grand_mirror(request_text(GRAND_MIRROR_URL))
    return ok_record(GRAND_MIRROR_URL, date, "third_party_mirror",
                     timestamp_type="mirror_fetch_age_estimate",
                     cash_buy=rates, denomination_labels=labels)


def collect():
    # Two banks, official cash selling only, ordered Cathay then Taishin.
    official = {
        "cathay": attempt(official_cathay, CATHAY_URL, "CATHAY_OFFICIAL"),
        "taishin": attempt(official_taishin, TAISHIN_URL, "TAISHIN_OFFICIAL"),
        "grand_superrich": attempt(official_grand, GRAND_URL, "GRAND_OFFICIAL"),
    }
    official["bank"] = choose_official_cash_bank(official)
    # Reference uses official bank CASH SELL with a clearly disclosed
    # third-party SuperRich quote; never reuses removed Taiwan Bank data.
    reference = {
        "bank": official["bank"].copy(),
        "grand_superrich": attempt(reference_grand, GRAND_MIRROR_URL, "GRAND_REFERENCE"),
    }
    return {"schema_version": 2,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "official": official, "reference": reference}


def self_test():
    assert banknote_match("USD", "USD 100")
    assert not banknote_match("USD", "USD 50")
    assert banknote_match("EUR", "EUR 500-100")
    assert not banknote_match("EUR", "EUR 50")
    assert banknote_match("JPY", "JPY 10000 - 5000")
    assert not banknote_match("JPY", "JPY 1000")
    assert banknote_match("KRW", "KRW") and not banknote_match("KRW", "KRW 1000")
    assert banknote_match("CNY", "CNY 100") and not banknote_match("CNY", "CNY 50")
    table = """<table>
    <tr><td>USA</td><td>USD 50</td><td>33.12</td><td>33.19</td></tr>
    <tr><td>USA</td><td>USD 100</td><td>33.67</td><td>33.77</td></tr>
    <tr><td>Europe</td><td>EUR 500-100</td><td>37.55</td><td>37.75</td></tr>
    <tr><td>Japan</td><td>JPY 10000 - 5000</td><td>0.2135</td><td>0.2150</td></tr>
    <tr><td>Korea</td><td>KRW</td><td>0.0254</td><td>0.0256</td></tr>
    <tr><td>Korea</td><td>KRW 1000</td><td>0.0244</td><td>0.0250</td></tr>
    <tr><td>China</td><td>CNY 100</td><td>5.04</td><td>5.07</td></tr>
    <tr><td>Taiwan</td><td>TWD</td><td>1.03</td><td>1.04</td></tr></table>"""
    rates, denoms = parse_grand_table(table)
    assert rates["USD"] == 33.67 and rates["KRW"] == 0.0254
    assert denoms["JPY"] == "JPY 10000-5000"
    grand_div = """<div>Last Update 15:44:40 27/Oct/2026</div>
    <div class="gsr-rate-row"><div class="gsr-rate-currency-box">
    <div class="gsr-rate-currency">USD 100</div></div>
    <div class="gsr-rate-buy">33.69</div><div class="gsr-rate-sell">33.74</div></div>
    <div class="gsr-rate-row"><div class="gsr-rate-currency">EUR 500-100</div>
    <div class="gsr-rate-buy">37.55</div><div class="gsr-rate-sell">37.70</div></div>
    <div class="gsr-rate-row"><div class="gsr-rate-currency">JPY 10000 - 5000</div>
    <div class="gsr-rate-buy">0.2135</div><div class="gsr-rate-sell">0.2150</div></div>
    <div class="gsr-rate-row"><div class="gsr-rate-currency">KRW</div>
    <div class="gsr-rate-buy">0.0255</div><div class="gsr-rate-sell">0.0257</div></div>
    <div class="gsr-rate-row"><div class="gsr-rate-currency">CNY 100</div>
    <div class="gsr-rate-buy">5.04</div><div class="gsr-rate-sell">5.07</div></div>
    <div class="gsr-rate-row"><div class="gsr-rate-currency">TWD</div>
    <div class="gsr-rate-buy">1.03</div><div class="gsr-rate-sell">1.04</div></div>"""
    div_prices, _ = parse_grand_table(grand_div)
    assert div_prices["USD"] == 33.69 and div_prices["TWD"] == 1.03
    assert parse_grand_timestamp(grand_div).hour == 15
    cathay_fixture = """<p>資料時間 Board time： 2026年10月29日 09:18:27</p>
        <div>美元USD 歷史走勢 項目 Item 銀行買進 Bank buy 銀行賣出 Bank sell
        即期匯率 32.4100 32.5100 數位通路優惠匯率 32.4400 32.4800 現鈔匯率 32.1300 32.7300</div>
        <div>歐元EUR 歷史走勢 現鈔匯率 35.5400 36.7200</div>
        <div>日圓JPY 歷史走勢 現鈔匯率 0.1992 0.2102</div>
        <div>人民幣CNY 歷史走勢 現鈔匯率 4.7300 4.9200</div>"""
    old = globals()["assert_fresh"]
    try:
        globals()["assert_fresh"]=lambda *args,**kwargs:None
        ctime,crates=parse_cathay_cash_rates(cathay_fixture)
        assert crates == {"USD":32.73,"EUR":36.72,"JPY":.2102,"CNY":4.92}
        taishin_fixture = """現鈔賣出 資料來源：台新銀行　更新日期：2026年10月29日 AM09時17分
        <table><tr><th>幣別</th><th>現鈔賣匯</th></tr>
        <tr><td>美元USD</td><td>32.6860</td></tr>
        <tr><td>歐元EUR</td><td>36.6830</td></tr>
        <tr><td>日圓JPY</td><td>0.2096</td></tr>
        <tr><td>人民幣CNY</td><td>4.9095</td></tr>
        </table>"""
        ttime,trates=parse_taishin_cash_rates(taishin_fixture)
        assert trates == {"USD":32.686,"EUR":36.683,"JPY":.2096,"CNY":4.9095}
    finally:
        globals()["assert_fresh"]=old
    fake={
      "cathay":ok_record(CATHAY_URL,ctime,"official_direct",
                 cash_sell={"USD":32.73,"EUR":36.72,"JPY":.2102,"CNY":4.92}),
      "taishin":ok_record(TAISHIN_URL,ttime,"official_direct",
                 cash_sell={"USD":32.686,"EUR":36.683,"JPY":.2096,"CNY":4.9095}),
    }
    fallback=choose_official_cash_bank(fake)
    assert fallback["cash_sell"]["USD"]==32.73
    assert fallback["currency_sources"]["USD"]["bank"]=="cathay"
    assert fallback["unsupported"]==["KRW"]
    fake["cathay"]["cash_sell"].pop("CNY")
    fallback=choose_official_cash_bank(fake)
    assert fallback["currency_sources"]["USD"]["bank"]=="cathay"
    assert fallback["currency_sources"]["CNY"]["bank"]=="taishin"
    fake["cathay"]=failure_record(CATHAY_URL,"blocked")
    fallback=choose_official_cash_bank(fake)
    assert fallback["currency_sources"]["USD"]["bank"]=="taishin"
    assert fallback["unsupported"]==["KRW"]
    print("Offline Cathay-Taishin cash fallback and banknote tests passed")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return
    payload = collect()
    previous = None
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    # Do not lose a last-known official/referenced quote: archive only as
    # explicit *historical*, never as today's status or current main calculation.
    if previous and previous.get("schema_version") == 2:
        for group in ("official", "reference"):
            names = ("cathay", "taishin", "grand_superrich") if group == "official" else ("grand_superrich",)
            for provider in names:
                prior = previous.get(group, {}).get(provider, {})
                rec = payload[group][provider]
                # A historical record from another website must never survive
                # when the user changes one official provider to another.
                if prior.get("source") != rec.get("source"):
                    prior = {}
                if rec["status"] == "failed" and prior.get("status") == "ok":
                    rec["last_successful"] = {
                        k: prior[k] for k in ("quoted_at", "source", "cash_sell",
                                             "cash_buy", "denomination_labels")
                        if k in prior
                    }
                elif (rec["status"] == "failed" and prior.get("last_successful")
                      and prior["last_successful"].get("source") == rec.get("source")):
                    rec["last_successful"] = prior["last_successful"]
                elif rec["status"] == "ok" and prior.get("status") == "ok":
                    # Do not let a lagging site overwrite newer quote value.
                    if datetime.fromisoformat(rec["quoted_at"]) < datetime.fromisoformat(prior["quoted_at"]):
                        print(f"{group}/{provider}: older quote, mark failed; preserve historical last-successful")
                        payload[group][provider] = failure_record(rec["source"],
                            "取得的牌告時間早於先前記錄，不可視為最新官方報價")
                        payload[group][provider]["last_successful"] = {
                            k: prior[k] for k in ("quoted_at", "source", "cash_sell",
                                                 "cash_buy", "denomination_labels") if k in prior
                        }
    # Derived bank cash source is calculated fresh each run, not carried over.
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, OUT)
    print("Saved separately attributed statuses:", "official",
          {k:v["status"] for k,v in payload["official"].items()}, "reference",
          {k:v["status"] for k,v in payload["reference"].items()})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("DATA STATUS UPDATE FAILED; existing snapshot untouched:", exc, file=sys.stderr)
        sys.exit(1)
