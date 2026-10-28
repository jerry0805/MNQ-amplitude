#!/usr/bin/env python3
"""每日更新：從期交所抓台指期(TX)近月合約的日盤/夜盤資料，輸出 docs/data.json

日盤 = 一般交易時段 08:45~13:45
夜盤 = 盤後交易時段 前一晚 15:00~當日 05:00（期交所以夜盤「結束那天」為交易日期）
全日盤 = 同一交易日的夜盤 + 日盤，首尾相連
振幅 = 最高 - 最低；百分比 = 振幅 / 該時段開盤價（全日盤用夜盤開盤價）
"""
import io
import json
import sys
import time
import datetime as dt
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.taifex.com.tw/cht/3/futDataDown"
KEEP = 80             # JSON 保留最近幾個交易日
LOOKBACK_DAYS = 150   # 往前抓幾個日曆天
MIN_ROWS = 20         # 少於這個數量視為抓取異常，不覆蓋舊資料
OUT = Path(__file__).parent / "docs" / "data.json"
TW = dt.timezone(dt.timedelta(hours=8))


def fetch(start: dt.date, end: dt.date) -> pd.DataFrame:
    payload = {
        "down_type": "1",
        "commodity_id": "TX",
        "queryStartDate": start.strftime("%Y/%m/%d"),
        "queryEndDate": end.strftime("%Y/%m/%d"),
    }
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(
                URL, data=payload, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (tx-amplitude-site)"},
            )
            r.raise_for_status()
            text = r.content.decode("big5", errors="ignore")
            df = pd.read_csv(io.StringIO(text), index_col=False)
            df.columns = [c.strip() for c in df.columns]
            return df
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"期交所下載失敗：{last_err}")


def load() -> pd.DataFrame:
    end = dt.datetime.now(TW).date()
    start = end - dt.timedelta(days=LOOKBACK_DAYS)
    parts, cur = [], start
    while cur <= end:  # 單次查詢以約一個月為限，分段抓
        nxt = min(cur + dt.timedelta(days=28), end)
        parts.append(fetch(cur, nxt))
        cur = nxt + dt.timedelta(days=1)
    df = pd.concat(parts, ignore_index=True)

    df = df[df["契約"].astype(str).str.strip() == "TX"].copy()
    month = df["到期月份(週別)"].astype(str).str.strip()
    df = df[~month.str.contains("/")].copy()  # 排除價差單
    df["month"] = month
    df["date"] = pd.to_datetime(df["交易日期"].astype(str).str.strip())
    df["sess"] = df["交易時段"].astype(str).str.strip()
    for c in ["開盤價", "最高價", "最低價", "收盤價"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["開盤價", "最高價", "最低價"])
    return df.drop_duplicates(["date", "sess", "month"])


def near_month(df: pd.DataFrame):
    """每個交易日以一般時段最近月合約為準；盤後沿用同一合約，沒有就取盤後最近月。"""
    day = df[df.sess == "一般"]
    night = df[df.sess == "盤後"]
    near = day.groupby("date")["month"].min()

    d = day.merge(near.rename("near"), left_on="date", right_index=True)
    d = d[d["month"] == d["near"]].set_index("date").sort_index()

    n = night.merge(near.rename("near"), left_on="date", right_index=True, how="left")
    same = n[n["month"] == n["near"]]
    other = n[~n["date"].isin(same["date"])]
    if len(other):
        other = other.loc[other.groupby("date")["month"].idxmin()]
    n = pd.concat([same, other]).set_index("date").sort_index()

    d = d[~d.index.duplicated()]
    n = n[~n.index.duplicated()]
    return d, n


def num(x):
    return None if pd.isna(x) else float(x)


def session(row):
    if row is None:
        return None
    o, h, l = float(row["開盤價"]), float(row["最高價"]), float(row["最低價"])
    return {
        "open": o, "high": h, "low": l, "close": num(row["收盤價"]),
        "amp": h - l, "pct": round((h - l) / o * 100, 3),
    }


def build_rows(day: pd.DataFrame, night: pd.DataFrame) -> list:
    rows = []
    for d in sorted(set(day.index) | set(night.index)):
        dr = day.loc[d] if d in day.index else None
        nr = night.loc[d] if d in night.index else None
        ds, ns = session(dr), session(nr)

        full = None
        if ds and ns:  # 兩段都有才算全日盤（當日日盤未收盤時先留空）
            h, l, o = max(ds["high"], ns["high"]), min(ds["low"], ns["low"]), ns["open"]
            full = {"open": o, "high": h, "low": l, "close": ds["close"],
                    "amp": h - l, "pct": round((h - l) / o * 100, 3)}

        rows.append({
            "date": d.strftime("%Y-%m-%d"),
            "contract": (dr if dr is not None else nr)["month"],
            "day": ds, "night": ns, "full": full,
        })
    return rows[-KEEP:]


def main():
    day, night = near_month(load())
    rows = build_rows(day, night)
    if len(rows) < MIN_ROWS:
        sys.exit(f"資料不足（只有 {len(rows)} 天），不更新 data.json")

    payload = {
        "updated": dt.datetime.now(TW).strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已寫入 {OUT}，共 {len(rows)} 個交易日，最新 {rows[-1]['date']}")


if __name__ == "__main__":
    main()
