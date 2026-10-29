# 台指期振幅監控

每個交易日自動從期交所抓台指期(TX)近月合約，計算日盤／夜盤／全日盤的平均振幅，網頁顯示 5／10／20／60 日平均、走勢圖與明細。

## 架構

- `fetch_tx.py`：下載資料並輸出 `docs/data.json`
- `docs/index.html`：靜態頁面，讀取 `data.json` 畫圖
- `.github/workflows/update.yml`：每週一到週五台灣時間 15:30 自動執行並提交新資料

## MNQ 頁面

網頁上方的「MNQ」分頁（網址後加 `#mnq` 可直接開啟）顯示 MNQ（微型那斯達克100期貨）的全日盤振幅，資料由 `fetch_mnq.py` 從 Yahoo Finance 的 `MNQ=F` 日線取得，輸出 `docs/mnq.json`。
台指期與 MNQ 共用同一個頁面 `docs/index.html`；`docs/mnq.html` 只是把舊連結導向主頁。
排程在 `.github/workflows/update-mnq.yml`，每週一到五 UTC 22:30（台灣時間隔日 06:30，CME 日盤收盤後）執行。
每口金額 = 振幅 × US$2。Yahoo 的日線與 TradingView 或券商 K 棒可能有些微差異，建議挑一天核對最高、最低價。

## WTI 原油分頁

網頁上方的「WTI 原油」分頁（網址後加 `#wti` 可直接開啟）顯示 WTI 原油期貨的全日盤振幅，單位是美元／桶。
資料由 `fetch_futures.py wti` 從 Yahoo Finance 的 `CL=F` 日線取得，輸出 `docs/wti.json`，排程在 `.github/workflows/update-wti.yml`（每週一到五台灣時間隔日 06:40）。
每口金額：CL 每 1 美元 US$1,000，MCL（微型）每 1 美元 US$100。

MNQ 與 WTI 共用 `fetch_futures.py`；`fetch_mnq.py` 只是轉接檔，讓舊的 MNQ 排程繼續可用。
之後要加其他商品，在 `fetch_futures.py` 的 `MARKETS` 加一行、`docs/index.html` 的 `MARKETS` 加一段設定、再複製一份 workflow 即可。

### WTI 分頁顯示內容（均價／最高／最低）

WTI 分頁顯示 5／10／20／60 日的日均價平均、期間最高價與最低價。
日均價 = 當日成交量加權均價（VWAP）：`fetch_futures.py` 抓 Yahoo 1 小時線，每根取 (高+低+收)/3 乘成交量，
依 CME 交易日（前一日 17:00 CT 至當日 16:00 CT）加總成交金額 ÷ 成交量。N 日均價 = 最近 N 個交易日 VWAP 的平均；
卡片另列整段期間的量加權均價（總成交金額 ÷ 總成交量）。
小時線抓不到、或某天沒有成交量時，退回 (開+高+低+收)/4，資料裡 `avg_src` 標為 `ohlc4`，網頁以 * 或「含 N 日估算」提示。
這是小時線近似值，與券商的逐筆 VWAP 會有小差距；`CL=F` 換月前後的量可能有跳動。

## 部署（GitHub Pages，免費）

1. 在 GitHub 建立新 repo，把這個資料夾的內容全部上傳。
2. Settings → Pages → Source 選 `Deploy from a branch`，Branch 選 `main`，資料夾選 `/docs`。
3. 到 Actions 頁籤啟用 workflow，點 `update-tx-amplitude` → `Run workflow` 手動跑第一次。
4. 約一分鐘後，網站在 `https://<你的帳號>.github.io/<repo 名稱>/`。

## 若 GitHub 的主機被期交所擋下

Actions 的主機在海外，若 workflow 在下載步驟失敗（連線被拒或逾時），可改在台灣的電腦或主機上跑：

```bash
pip install -r requirements.txt
python fetch_tx.py          # 更新 docs/data.json
cd docs && python -m http.server 8000   # 在 http://localhost:8000 看網頁
```

排程範例（Linux/macOS crontab，每週一到五 15:30）：

```
30 15 * * 1-5 cd /path/to/tx-amplitude-site && python fetch_tx.py
```

## 定義

- 日盤：一般交易時段 08:45–13:45
- 夜盤：前一晚 15:00 至當日 05:00（期交所以夜盤結束那天為交易日期）
- 全日盤：同一交易日的夜盤＋日盤
- 振幅 = 最高價 − 最低價；百分比 = 振幅 ÷ 該時段開盤價（全日盤用夜盤開盤價）
- 近月合約：每個交易日以一般時段最近月份為準，結算日當天夜盤沒有近月時改用盤後最近月
