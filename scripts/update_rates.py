#!/usr/bin/env python3
"""Separate OFFICIAL cash quotations from THIRD-PARTY reference quotations.

Never promote a mirrored quote to official. Missing official quotes are failures,
not permission to silently substitute estimated or market rates.
"""
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BOT_URL = "https://rate.bot.com.tw/xrt?Lang=zh-TW"
BOT_CSV_URL = "https://rate.bot.com.tw/xrt/flcsv/0/day"
GRAND_URL = "https://www.grandsuperrich.com/rate.php"
BOT_MIRROR_URL = "https://www.findrate.tw/bank/29/"
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


def parse_bot_timestamp(html):
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(
        r"(?:牌價最新掛牌時間|Quoted\s+(?:Date|Time)|Latest\s+Quotation\s+Time)"
        r"\s*[:：]?\s*(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})"
        r"\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", text, re.I
    )
    if not m:
        raise ValueError("臺銀官方頁面缺少可驗證的牌告時間")
    y, mon, d, h, minute, sec = m.groups()
    return datetime(int(y), int(mon), int(d), int(h), int(minute),
                    int(sec or 0), tzinfo=TW)


def parse_bot_html(html):
    soup = BeautifulSoup(html, "html.parser")
    rates = {}
    for tr in soup.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        content = tr.get_text(" ", strip=True)
        match = re.search(r"\b(USD|EUR|JPY|KRW|CNY)\b", content)
        if not match:
            continue
        ccy = match.group(1)
        # Bank of Taiwan labels these cells as CASH RATE; ignore spot cells.
        cash_cells = tr.select("td.rate-content-cash")
        sell_cell = cash_cells[1] if len(cash_cells) >= 2 else None
        if sell_cell is None:
            for td in cells:
                header = (td.get("data-table") or "").strip().lower()
                cls = " ".join(td.get("class", [])).lower()
                if ("本行賣出" in header or "cash selling" in header or
                    ("cash" in cls and "sell" in cls)):
                    sell_cell = td
                    break
        if sell_cell is None:
            raise ValueError(f"臺銀 {ccy} 找不到現鈔賣出欄位")
        m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", sell_cell.get_text(" ", strip=True))
        if not m:
            raise ValueError(f"臺銀 {ccy} 現鈔賣出欄位沒有價格")
        rates[ccy] = price(ccy, m.group(1))
    if set(rates) != set(BANK_CURRENCIES):
        raise ValueError(f"臺銀官方現鈔賣出價不完整: {sorted(rates)}")
    return rates


def parse_bot_csv(body):
    rates = {}
    for row in csv.reader(io.StringIO(body.lstrip("\ufeff"))):
        if len(row) <= 12:
            continue
        code = row[0].strip().upper()
        if code in BANK_CURRENCIES:
            rates[code] = price(code, row[12].strip())
    if set(rates) != set(BANK_CURRENCIES):
        raise ValueError(f"臺銀官方 CSV 現鈔賣出價不完整: {sorted(rates)}")
    return rates


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


def bot_mirror(raw):
    """Read FindRate's **Taiwan Bank** cash SELL quotes (not spot sell).

    FindRate's /bank/29/ page includes a bank-wide quotation timestamp.
    We never substitute retrieval time for the published quotation time.
    """
    soup = BeautifulSoup(raw, "html.parser")
    content = soup.get_text(" ", strip=True)
    if not re.search(r"臺灣銀行|台灣銀行", content):
        raise ValueError("FindRate 頁面不屬於臺灣銀行")

    stamp_match = re.search(
        r"匯率更新時間\s*[:：]?\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
        r"\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        content
    )
    if not stamp_match:
        raise ValueError("FindRate 頁面缺少可驗證的「匯率更新時間」")
    y, month, d, hour, minute, seconds = stamp_match.groups()
    quoted_at = datetime(int(y), int(month), int(d), int(hour),
                         int(minute), int(seconds or 0), tzinfo=TW)

    rates = {}
    matched_table = False
    for table in soup.select("table"):
        # Match the actual CASH SELL header, not SPOT SELL.
        headings = [[re.sub(r"\s+", "", th.get_text(" ", strip=True))
                     for th in row.find_all(["th", "td"], recursive=False)]
                    for row in table.select("tr")[:4]]
        cash_index = None
        for heading in headings:
            if "現鈔賣出" in heading and "幣別" in heading:
                cash_index = heading.index("現鈔賣出")
                break
        if cash_index is None:
            continue
        matched_table = True
        for tr in table.select("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) <= cash_index:
                continue
            currency_cell = cells[0].get_text(" ", strip=True)
            found = re.search(r"\b(USD|EUR|JPY|KRW|CNY)\b", currency_cell, re.I)
            if not found:
                continue
            code = found.group(1).upper()
            value = cells[cash_index].get_text(" ", strip=True).replace(",", "")
            if not re.fullmatch(r"\d+(?:\.\d+)?", value):
                raise ValueError(f"FindRate {code} 缺少有效的現鈔賣出價")
            new_price = price(code, value)
            if code in rates and rates[code] != new_price:
                raise ValueError(f"FindRate {code} 出現不一致的現鈔賣出價")
            rates[code] = new_price

    if not matched_table:
        raise ValueError("FindRate 找不到「幣別／現鈔賣出」牌告表")
    if set(rates) != set(BANK_CURRENCIES):
        raise ValueError("FindRate 現鈔賣出資料不完整：" +
                         ",".join(sorted(set(BANK_CURRENCIES) - set(rates))))

    # The timestamp on /bank/29/ may be old even if page downloads today.
    # Preserve the original date in the failure message for user visibility.
    assert_fresh(quoted_at, "FindRate 臺銀第三方牌告", hours=120)
    return quoted_at, rates


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


def official_bot():
    html = request_text(BOT_URL)
    date = parse_bot_timestamp(html)
    try:
        rates = parse_bot_html(html)
    except ValueError:
        rates = parse_bot_csv(request_text(BOT_CSV_URL))
    assert_fresh(date, "臺銀官方")
    return ok_record(BOT_URL, date, "official_direct", cash_sell=rates)


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


def reference_bot():
    date, rates = bot_mirror(request_text(BOT_MIRROR_URL))
    return ok_record(BOT_MIRROR_URL, date, "third_party_mirror",
                     timestamp_type="findrate_bank_quotation", cash_sell=rates)


def reference_grand():
    date, rates, labels = grand_mirror(request_text(GRAND_MIRROR_URL))
    return ok_record(GRAND_MIRROR_URL, date, "third_party_mirror",
                     timestamp_type="mirror_fetch_age_estimate",
                     cash_buy=rates, denomination_labels=labels)


def collect():
    # All four fetches are independent. No fallback is permitted within official.
    official = {
        "bot": attempt(official_bot, BOT_URL, "BOT_OFFICIAL"),
        "grand_superrich": attempt(official_grand, GRAND_URL, "GRAND_OFFICIAL"),
    }
    reference = {
        "bot": attempt(reference_bot, BOT_MIRROR_URL, "BOT_REFERENCE"),
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
    bot_html = """<span>牌價最新掛牌時間：2026/10/27 16:22</span><table>""" + "".join(
        f'<tr><td>{code}</td><td class="rate-content-cash">1</td>'
        f'<td class="rate-content-cash">{val}</td></tr>'
        for code,val in (("USD",32.8),("EUR",36.9),("JPY",.2099),("KRW",.0268),("CNY",4.94))
    ) + "</table>"
    assert parse_bot_timestamp(bot_html).hour == 16
    assert parse_bot_html(bot_html)["USD"] == 32.8
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
    # FindRate /bank/29/: spot-sell is deliberately different from cash-sell.
    findrate_html = """<html><h1>臺灣銀行牌告匯率表</h1>
    <p>匯率更新時間 : 2026-10-29 09:08</p><table>
    <tr><th>幣別</th><th>現鈔買入</th><th>現鈔賣出</th><th>即期買入</th><th>即期賣出</th></tr>
    <tr><td>美金 USD</td><td>31.00</td><td>32.15</td><td>31.35</td><td>31.86</td></tr>
    <tr><td>歐元 EUR</td><td>34.80</td><td>36.90</td><td>35.30</td><td>36.20</td></tr>
    <tr><td>日幣 JPY</td><td>0.189</td><td>0.207</td><td>0.190</td><td>0.199</td></tr>
    <tr><td>韓元 KRW</td><td>0.019</td><td>0.025</td><td>--</td><td>--</td></tr>
    <tr><td>人民幣 CNY</td><td>4.61</td><td>4.88</td><td>4.70</td><td>4.78</td></tr>
    </table></html>"""
    # Isolate fixed fixture parsing from the wall clock.
    original_freshness = globals()["assert_fresh"]
    try:
        globals()["assert_fresh"] = lambda dt, name, hours=120: None
        findrate_date, findrate_rates = bot_mirror(findrate_html)
    finally:
        globals()["assert_fresh"] = original_freshness
    assert findrate_date.isoformat() == "2026-10-29T09:08:00+08:00"
    assert findrate_rates == {"USD": 32.15, "EUR": 36.9, "JPY": 0.207,
                              "KRW": 0.025, "CNY": 4.88}
    try:
        bot_mirror(findrate_html.replace("2026-10-29", "2026-06-29"))
        raise AssertionError("outdated FindRate quote should be rejected")
    except ValueError as exc:
        assert "過期" in str(exc) or "不合理" in str(exc)
    assert failure_record(BOT_URL, ValueError("blocked"))["status"] == "failed"
    print("Offline source-separation, currency, banknote and timestamp tests passed")


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
            for provider in ("bot", "grand_superrich"):
                prior = previous.get(group, {}).get(provider, {})
                rec = payload[group][provider]
                if rec["status"] == "failed" and prior.get("status") == "ok":
                    rec["last_successful"] = {
                        k: prior[k] for k in ("quoted_at", "source", "cash_sell",
                                             "cash_buy", "denomination_labels")
                        if k in prior
                    }
                elif rec["status"] == "failed" and prior.get("last_successful"):
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
