#!/usr/bin/env python3
"""每日更新：抓 MNQ（微型那斯達克100期貨）近月連續合約日線，輸出 docs/mnq.json

資料來源：Yahoo Finance (MNQ=F)。
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
URL = f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}"
KEEP = 80        # JSON 保留最近幾個交易日
MIN_ROWS = 20    # 少於這個數量視為抓取異常，不覆蓋舊資料
OUT = Path(__file__).parent / "docs" / "mnq.json"
TW = ZoneInfo("Asia/Taipei")
CT = ZoneInfo("America/Chicago")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def fetch_raw() -> dict:
    last_err = None
    for attempt in range(4):
        try:
            r = requests.get(URL, params={"range": "1y", "interval": "1d"},
                             headers=HEADERS, timeout=30)
            r.raise_for_status()
            result = r.json()["chart"]["result"]
            if not result:
                raise RuntimeError("Yahoo 回傳空結果")
            return result[0]
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Yahoo Finance 下載失敗：{last_err}")


def is_complete(d: dt.date, now_ct: dt.datetime) -> bool:
    """CME 日盤 16:00 CT 收盤；還沒收完或已開始的下一個交易日的日線不採用。"""
    if d < now_ct.date():
        return True
    if d == now_ct.date():
        return now_ct.time() >= dt.time(16, 5)
    return False


def parse(res: dict, now_ct: dt.datetime) -> list:
    tz = ZoneInfo(res["meta"].get("exchangeTimezoneName", "America/New_York"))
    q = res["indicators"]["quote"][0]
    rows = {}
    for i, t in enumerate(res.get("timestamp", [])):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        o, h, l, c = (float(v) for v in vals)
        d = dt.datetime.fromtimestamp(t, tz).date()
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
    rows = parse(fetch_raw(), now_ct)[-KEEP:]
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
