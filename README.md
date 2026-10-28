# 台指期振幅監控

每個交易日自動從期交所抓台指期(TX)近月合約，計算日盤／夜盤／全日盤的平均振幅，網頁顯示 5／10／20／60 日平均、走勢圖與明細。

## 架構

- `fetch_tx.py`：下載資料並輸出 `docs/data.json`
- `docs/index.html`：靜態頁面，讀取 `data.json` 畫圖
- `.github/workflows/update.yml`：每週一到週五台灣時間 15:30 自動執行並提交新資料

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
