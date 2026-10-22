#!/usr/bin/env python3
"""Collect Bank of Taiwan CASH SELL and Grand SuperRich CASH BUY quotations.

Never substitute spot/market rates; reject old, missing, or invalid source data.
Requires: requests, beautifulsoup4 (see GitHub workflow).
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

BOT_URL = "https://rate.bot.com.tw/xrt"
BOT_CSV_URL = "https://rate.bot.com.tw/xrt/flcsv/0/day"
GRAND_URL = "https://www.grandsuperrich.com/rate.php"
CURRENCIES = ("USD", "EUR", "JPY", "KRW", "CNY")
ALL = ("TWD", *CURRENCIES)
BOUNDS = {
    "TWD": (0.6, 1.5),
    "USD": (20.0, 50.0),
    "EUR": (25.0, 60.0),
    "JPY": (0.12, 0.40),
    "KRW": (0.01, 0.06),
    "CNY": (3.0, 8.0),
}
TAIPEI = ZoneInfo("Asia/Taipei")
BANGKOK = ZoneInfo("Asia/Bangkok")
OUT = Path(__file__).resolve().parents[1] / "rates.json"


def request_text(url):
    r = requests.get(
        url,
        timeout=(12, 30),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Thai-Exchange/1.0; public cash-rate check)",
            "Accept": "text/html,text/csv,*/*",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        params={"_": int(datetime.now(timezone.utc).timestamp())},
    )
    r.raise_for_status()
    r.encoding = "utf-8-sig"
    if not r.text.strip():
        raise ValueError("Empty response: " + url)
    return r.text


def check_range(code, value):
    low, high = BOUNDS[code]
    if not (low <= value <= high):
        raise ValueError(f"{code}: suspicious/out-of-range cash quotation {value}")
    return value


def bot_cash_sell(csv_text):
    rates = {}
    for row in csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))):
        if len(row) <= 12:
            continue
        code = row[0].strip().upper().replace("\ufeff", "")
        if code not in CURRENCIES:
            continue
        # Official BOT flcsv: first side = bank BUY; second side
        # starts at index 11, and CASH SELL is index 12.
        rates[code] = check_range(code, float(row[12].strip()))
    if set(rates) != set(CURRENCIES):
        raise ValueError(f"BOT cash sell incomplete: {sorted(rates)}; response_prefix={csv_text[:260]!r}")
    return rates


def bot_quote_timestamp(html):
    txt = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(
        r"(?:牌價最新掛牌時間|Quoted\s+(?:Date|Time)|Latest\s+Quotation\s+Time)"
        r"\s*[:：]?\s*(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})"
        r"\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        txt, re.I
    )
    if not m:
        raise ValueError("BOT published quote timestamp not found")
    y, mo, d, h, minute, second = m.groups()
    return datetime(int(y), int(mo), int(d), int(h), int(minute),
                    int(second or 0), tzinfo=TAIPEI)


def grand_cash_buy(html):
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(" ", strip=True)
    m = re.search(
        r"Last\s+updated\s+exchange\s+rate\s*[:：]\s*"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})\s*[-–]\s*"
        r"(\d{1,2}:\d{2}:\d{2})", txt, re.I
    )
    if not m:
        raise ValueError("Grand SuperRich published quote timestamp not found")
    datepart = re.sub(r"\s+", " ", m.group(1)).replace(",", ",")
    if "," not in datepart:
        datepart = re.sub(r"(\d{1,2}) (\d{4})$", r"\1, \2", datepart)
    quoted_at = datetime.strptime(
        datepart + " " + m.group(2), "%B %d, %Y %H:%M:%S"
    ).replace(tzinfo=BANGKOK)

    rates = {}
    denomin = {}
    for tr in soup.select("tr"):
        cells = tr.find_all(["td"], recursive=False)
        if len(cells) < 2:
            continue
        row = " ".join(td.get_text(" ", strip=True) for td in cells)
        found = re.search(r"\b(TWD|USD|EUR|JPY|KRW|CNY)\b", row)
        if not found:
            continue
        code = found.group(1)
        if code in rates:
            continue  # first quotation uses the preferred large-banknote tier
        number_tokens = re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", row)
        if len(number_tokens) < 2:
            continue
        buying, selling = map(float, number_tokens[-2:])
        check_range(code, buying)
        if selling < buying:
            raise ValueError(f"Grand SuperRich {code}: buy > sell")
        rates[code] = buying
        denomin[code] = row[:120]

    if set(rates) != set(ALL):
        raise ValueError(f"Grand SuperRich cash buy incomplete: {sorted(rates)}")
    return rates, quoted_at, denomin


def verify_fresh(date_value, source, max_age_hours=120):
    now = datetime.now(timezone.utc)
    age = now - date_value.astimezone(timezone.utc)
    if age < -timedelta(hours=2) or age > timedelta(hours=max_age_hours):
        raise ValueError(
            f"{source} quotation date unacceptable: {date_value.isoformat()}, "
            f"age_hours={age.total_seconds()/3600:.1f}"
        )


def collect():
    bot_csv = request_text(BOT_CSV_URL)
    bot_html = request_text(BOT_URL)
    grand_html = request_text(GRAND_URL)

    bot_rates = bot_cash_sell(bot_csv)
    bot_date = bot_quote_timestamp(bot_html)
    grand_rates, grand_date, denominations = grand_cash_buy(grand_html)
    verify_fresh(bot_date, "BOT", max_age_hours=120)
    verify_fresh(grand_date, "Grand SuperRich", max_age_hours=120)

    return {
        "schema_version": 1,
        "providers": {
            "bot": {
                "source": BOT_URL,
                "quoted_at": bot_date.isoformat(),
                "cash_sell": bot_rates,
            },
            "grand_superrich": {
                "source": GRAND_URL,
                "quoted_at": grand_date.isoformat(),
                "cash_buy": grand_rates,
                "denomination_labels": denominations,
            },
        },
    }


def self_test():
    csv_fixture = (
        "幣別,匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,"
        "遠期120天,遠期150天,遠期180天,匯率,現金,即期\n"
        + "\n".join(
            f"{cc},0,0,0,0,0,0,0,0,0,0,0,{v},0"
            for cc, v in [("USD", 32.7), ("EUR", 37.0), ("JPY", 0.21),
                          ("KRW", 0.026), ("CNY", 4.95)]
        )
    )
    assert bot_cash_sell(csv_fixture)["JPY"] == 0.21
    assert bot_quote_timestamp(
        "<span>牌價最新掛牌時間：2026/10/22 09:08</span>"
    ).hour == 9
    html_fixture = """<div>Last updated exchange rate: October 22, 2026 - 11:45:12</div>
      <table><tr><th>Country</th><th>Currency</th><th>Buying Rate</th><th>Selling Rate</th></tr>
      <tr><td>USA</td><td>USD 100</td><td>33.5</td><td>33.6</td></tr>
      <tr><td>European Union</td><td>EUR 500-100</td><td>38.0</td><td>38.1</td></tr>
      <tr><td>Japan</td><td>JPY 10000 - 5000</td><td>0.2120</td><td>0.2130</td></tr>
      <tr><td>Korea</td><td>KRW</td><td>0.025</td><td>0.026</td></tr>
      <tr><td>China</td><td>CNY 100</td><td>5.02</td><td>5.04</td></tr>
      <tr><td>Taiwan</td><td>TWD</td><td>1.03</td><td>1.04</td></tr></table>"""
    vals, dt, _ = grand_cash_buy(html_fixture)
    assert len(vals) == 6 and vals["CNY"] == 5.02
    assert dt.hour == 11 and dt.tzinfo == BANGKOK
    print("Offline parser tests passed")


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
    if previous and previous.get("providers") == payload["providers"]:
        print("No quotation changes; no file write")
        return
    payload["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, OUT)
    print("Updated rates.json. BOT:",
          payload["providers"]["bot"]["quoted_at"],
          "Grand:", payload["providers"]["grand_superrich"]["quoted_at"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("RATE UPDATE FAILED (previous published data untouched):", exc, file=sys.stderr)
        sys.exit(1)
