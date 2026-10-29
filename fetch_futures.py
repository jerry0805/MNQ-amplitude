#!/usr/bin/env python3
"""每日更新：抓期貨近月連續合約日線（Yahoo Finance），輸出 docs/<名稱>.json

用法：  python fetch_futures.py mnq     # MNQ 微型那斯達克100 -> docs/mnq.json
        python fetch_futures.py wti     # WTI 原油 (CL)       -> docs/wti.json

先直接呼叫 Yahoo 的 chart API（兩個主機），失敗再改用 yfinance 套件；
全部失敗時會列出每次嘗試的錯誤原因。
日線涵蓋 CME Globex 一個完整交易日（前一日 17:00 CT ~ 當日 16:00 CT），視為全日盤。
振幅 = 最高 - 最低；百分比 = 振幅 / 開盤價。
日均價：設了 "vwap": True 的商品（wti）改抓 1 小時線，每根用 (高+低+收)/3 乘成交量，
  依 CME 交易日（前一日 17:00 CT ~ 當日 16:00 CT）加總成交金額 ÷ 成交量 = 當日 VWAP；
  某天完全沒成交量、或小時線抓不到時，退回 AVG_METHOD 的日線算法並在 avg_src 標記 "ohlc4"。
  N 日均價 = 最近 N 個交易日 VWAP 的平均（不是收盤價平均），另存 vol / pv 供量加權用。
新增商品只要在 MARKETS 加一行。
"""
import json
import sys
import time
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

MARKETS = {
    "mnq": {"symbol": "MNQ=F", "out": "mnq.json"},   # 每點 US$2
    "wti": {"symbol": "CL=F",  "out": "wti.json", "vwap": True},   # CL 每 1 美元 US$1,000；MCL 每 1 美元 US$100
}
URL_TMPL = "https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
AVG_METHOD = "ohlc4"   # 退回日線時用的算法： ohlc4=(開+高+低+收)/4；hlc3=(高+低+收)/3；mid=(高+低)/2
AVG_FUNCS = {
    "ohlc4": lambda o, h, l, c: (o + h + l + c) / 4,
    "hlc3":  lambda o, h, l, c: (h + l + c) / 3,
    "mid":   lambda o, h, l, c: (h + l) / 2,
}
KEEP = 80        # JSON 保留最近幾個交易日
MIN_ROWS = 20    # 少於這個數量視為抓取異常，不覆蓋舊資料
DOCS = Path(__file__).parent / "docs"
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


def fetch_chart_result(symbol: str, errors: list, interval: str = "1d", rng: str = "1y"):
    for host in ("query1", "query2"):
        url = URL_TMPL.format(host=host, symbol=symbol)
        for attempt in (1, 2):
            tag = f"{host} 第{attempt}次"
            try:
                r = requests.get(url, params={"range": rng, "interval": interval},
                                 headers=HEADERS, timeout=30)
                if r.status_code != 200:
                    errors.append(f"{tag}：HTTP {r.status_code} {r.text[:120]!r}")
                    time.sleep(3)
                    continue
                result = r.json()["chart"]["result"]
                if not result:
                    errors.append(f"{tag}：回傳空結果")
                    continue
                return result[0]
            except Exception as e:  # noqa: BLE001
                errors.append(f"{tag}：{type(e).__name__}: {e}")
                time.sleep(3)
    return None


def fetch_chart_bars(symbol: str, errors: list):
    res = fetch_chart_result(symbol, errors)
    bars = bars_from_chart(res) if res else None
    if res and not bars:
        errors.append("chart API：沒有任何有效日線")
    return bars or None


def hourly_from_chart(res: dict) -> list:
    """Yahoo chart API 1h 結果 -> [(CT 時間, o, h, l, c, volume), ...]"""
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res.get("timestamp", [])):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        vol = q["volume"][i] if q.get("volume") else None
        out.append((dt.datetime.fromtimestamp(t, CT), *map(float, vals), float(vol or 0)))
    return out


def fetch_hourly(symbol: str, errors: list):
    res = fetch_chart_result(symbol, errors, "1h", "6mo")
    if res:
        bars = hourly_from_chart(res)
        if bars:
            return bars, "Yahoo chart API"
        errors.append("chart API：沒有任何有效小時線")
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period="6mo", interval="1h", auto_adjust=False)
        out = []
        for idx, row in df.iterrows():
            vals = [row["Open"], row["High"], row["Low"], row["Close"]]
            if any(v != v for v in vals):
                continue
            vol = row.get("Volume", 0)
            ts = idx.tz_convert(CT) if idx.tzinfo else idx.replace(tzinfo=CT)
            out.append((ts.to_pydatetime(), *map(float, vals), float(vol) if vol == vol else 0.0))
        if out:
            return out, "yfinance"
        errors.append("yfinance：回傳空小時線")
    except Exception as e:  # noqa: BLE001
        errors.append(f"yfinance 小時線：{type(e).__name__}: {e}")
    return None, None


def fetch_yf_bars(symbol: str, errors: list):
    try:
        import yfinance as yf
    except ImportError:
        errors.append("yfinance 套件未安裝")
        return None
    try:
        df = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=False)
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


def get_bars(symbol: str) -> list:
    errors: list = []
    bars = fetch_chart_bars(symbol, errors)
    if bars:
        print("資料來源：Yahoo chart API")
        return bars
    bars = fetch_yf_bars(symbol, errors)
    if bars:
        print("資料來源：yfinance（chart API 失敗：" + "；".join(errors[:2]) + "）")
        return bars
    print(f"{symbol}：所有資料來源都失敗，詳細原因：", file=sys.stderr)
    for e in errors:
        print("  - " + e, file=sys.stderr)
    raise RuntimeError(f"無法取得 {symbol} 資料")


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
        if o <= 0:  # 防呆：開盤價不應為 0 或負數，避免百分比算錯
            continue
        rows[d] = {
            "date": d.strftime("%Y-%m-%d"),
            "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2),
            "avg": round(AVG_FUNCS[AVG_METHOD](o, h, l, c), 3),
            "amp": round(h - l, 2), "pct": round((h - l) / o * 100, 3),
        }
    return [rows[d] for d in sorted(rows)]


def trade_date(t: dt.datetime) -> dt.date:
    """CME 交易日：17:00 CT 之後的 K 棒算下一個日曆日（週日晚盤 -> 週一）。"""
    return t.date() + dt.timedelta(days=1) if t.hour >= 17 else t.date()


def build_rows_vwap(hourly: list, now_ct: dt.datetime) -> list:
    groups: dict = {}
    for b in sorted(hourly, key=lambda x: x[0]):
        groups.setdefault(trade_date(b[0]), []).append(b)
    rows = []
    for d in sorted(groups):
        bs = groups[d]
        if d.weekday() >= 5 or len(bs) < 3 or not is_complete(d, now_ct):
            continue
        o, c = bs[0][1], bs[-1][4]
        h, l = max(b[2] for b in bs), min(b[3] for b in bs)
        if o <= 0:
            continue
        vol = sum(b[5] for b in bs)
        pv = sum((b[2] + b[3] + b[4]) / 3 * b[5] for b in bs)
        if vol > 0:
            avg, src = pv / vol, "vwap"
        else:
            avg, src, pv = AVG_FUNCS[AVG_METHOD](o, h, l, c), "ohlc4", 0.0
        rows.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2),
            "avg": round(avg, 3), "avg_src": src, "vol": int(vol), "pv": round(pv),
            "amp": round(h - l, 2), "pct": round((h - l) / o * 100, 3),
        })
    return rows


def get_rows(symbol: str, vwap: bool, now_ct: dt.datetime) -> list:
    if vwap:
        errors: list = []
        hourly, src = fetch_hourly(symbol, errors)
        if hourly:
            rows = build_rows_vwap(hourly, now_ct)
            if len(rows) >= MIN_ROWS:
                n = sum(r["avg_src"] == "vwap" for r in rows)
                print(f"小時線來源：{src}，{n}/{len(rows)} 天用成交量加權 VWAP")
                return rows
            errors.append(f"小時線只湊出 {len(rows)} 個完整交易日")
        print(f"{symbol}：小時線不可用，改用日線 OHLC4。原因：" + "；".join(errors), file=sys.stderr)
    rows = build_rows(get_bars(symbol), now_ct)
    for r in rows:
        r["avg_src"] = "ohlc4"
    return rows


def run(key: str):
    if key not in MARKETS:
        sys.exit(f"不認得的商品 {key!r}，可用：{', '.join(MARKETS)}")
    symbol, out = MARKETS[key]["symbol"], DOCS / MARKETS[key]["out"]
    now_ct = dt.datetime.now(CT)
    rows = get_rows(symbol, MARKETS[key].get("vwap", False), now_ct)[-KEEP:]
    if len(rows) < MIN_ROWS:
        sys.exit(f"資料不足（只有 {len(rows)} 天），不更新 {out.name}")

    payload = {
        "symbol": symbol,
        "updated": dt.datetime.now(TW).strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已寫入 {out}，共 {len(rows)} 個交易日，最新 {rows[-1]['date']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("用法：python fetch_futures.py <mnq|wti>")
    run(sys.argv[1].lower())
