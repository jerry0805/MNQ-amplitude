#!/usr/bin/env python3
"""每日更新：抓 MNQ（微型那斯達克100期貨）近月連續合約日線，輸出 docs/mnq.json

資料來源：Yahoo Finance (MNQ=F)。先直接呼叫 Yahoo 的 chart API（兩個主機），
失敗再改用 yfinance 套件；全部失敗時會列出每次嘗試的錯誤原因。
日線涵蓋 CME 一個完整交易日（前一日 17:00 CT ~ 當日 16:00 CT），視為全日盤。
振幅 = 最高 - 最低；百分比 = 振幅 / 開盤價。每口損益 = 振幅 x US$2（MNQ 每點 2 美元）。
"""
import json
import sys
import time
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SYMBOL = "MNQ=F"
URL_TMPL = "https://{host}.finance.yahoo.com/v8/finance/chart/" + SYMBOL
KEEP = 80        # JSON 保留最近幾個交易日
MIN_ROWS = 20    # 少於這個數量視為抓取異常，不覆蓋舊資料
OUT = Path(__file__).parent / "docs" / "mnq.json"
TW = ZoneInfo("Asia/Taipei")
CT = ZoneInfo("America/Chicago")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def bars_from_chart(res: dict) -> list:
    """Yahoo chart API 結果 -> [(date, open, high, low, close), ...]"""
    tz = ZoneInfo(res["meta"].get("exchangeTimezoneName", "America/New_York"))
    q = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(res.get("timestamp", [])):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        bars.append((dt.datetime.fromtimestamp(t, tz).date(), *map(float, vals)))
    return bars


def fetch_chart_bars(errors: list):
    for host in ("query1", "query2"):
        url = URL_TMPL.format(host=host)
        for attempt in (1, 2):
            tag = f"{host} 第{attempt}次"
            try:
                r = requests.get(url, params={"range": "1y", "interval": "1d"},
                                 headers=HEADERS, timeout=30)
                if r.status_code != 200:
                    errors.append(f"{tag}：HTTP {r.status_code} {r.text[:120]!r}")
                    time.sleep(3)
                    continue
                result = r.json()["chart"]["result"]
                if not result:
                    errors.append(f"{tag}：回傳空結果")
                    continue
                bars = bars_from_chart(result[0])
                if bars:
                    return bars
                errors.append(f"{tag}：沒有任何有效日線")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{tag}：{type(e).__name__}: {e}")
                time.sleep(3)
    return None


def fetch_yf_bars(errors: list):
    try:
        import yfinance as yf
    except ImportError:
        errors.append("yfinance 套件未安裝")
        return None
    try:
        df = yf.Ticker(SYMBOL).history(period="1y", interval="1d", auto_adjust=False)
        bars = []
        for idx, row in df.iterrows():
            vals = [row["Open"], row["High"], row["Low"], row["Close"]]
            if any(v != v for v in vals):  # NaN
                continue
            bars.append((idx.date(), *map(float, vals)))
        if bars:
            return bars
        errors.append("yfinance：回傳空資料（可能被 Yahoo 限流）")
    except Exception as e:  # noqa: BLE001
        errors.append(f"yfinance：{type(e).__name__}: {e}")
    return None


def get_bars() -> list:
    errors: list = []
    bars = fetch_chart_bars(errors)
    if bars:
        print("資料來源：Yahoo chart API")
        return bars
    bars = fetch_yf_bars(errors)
    if bars:
        print("資料來源：yfinance（chart API 失敗：" + "；".join(errors[:2]) + "）")
        return bars
    print("所有資料來源都失敗，詳細原因：", file=sys.stderr)
    for e in errors:
        print("  - " + e, file=sys.stderr)
    raise RuntimeError("無法取得 MNQ 資料")


def is_complete(d: dt.date, now_ct: dt.datetime) -> bool:
    """CME 日盤 16:00 CT 收盤；還沒收完或已開始的下一個交易日的日線不採用。"""
    if d < now_ct.date():
        return True
    if d == now_ct.date():
        return now_ct.time() >= dt.time(16, 5)
    return False


def build_rows(bars: list, now_ct: dt.datetime) -> list:
    rows = {}
    for d, o, h, l, c in bars:
        if not is_complete(d, now_ct):
            continue
        rows[d] = {
            "date": d.strftime("%Y-%m-%d"),
            "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2),
            "amp": round(h - l, 2), "pct": round((h - l) / o * 100, 3),
        }
    return [rows[d] for d in sorted(rows)]


def main():
    now_ct = dt.datetime.now(CT)
    rows = build_rows(get_bars(), now_ct)[-KEEP:]
    if len(rows) < MIN_ROWS:
        sys.exit(f"資料不足（只有 {len(rows)} 天），不更新 mnq.json")

    payload = {
        "symbol": SYMBOL,
        "updated": dt.datetime.now(TW).strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已寫入 {OUT}，共 {len(rows)} 個交易日，最新 {rows[-1]['date']}")


if __name__ == "__main__":
    main()
