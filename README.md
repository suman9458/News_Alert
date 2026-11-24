# Gold & Forex Alert Terminal

A real-time market intelligence and alert system for **Gold** and **Forex** news. Features an interactive web dashboard with **live audio chimes**, **browser push notifications**, **real-time filtering**, and automated Telegram alerts.

---

## ⚡ Features

- **Real-Time Market Terminal**: Sleek dark-mode dashboard displaying live headlines categorized into **Gold (XAU/USD)**, **Forex (Currencies)**, and **Fed & Rates (FOMC/Inflation)**.
- **Audio Chime Alerts**: Built-in Web Audio API synthesizer that plays a two-tone financial alert chime whenever new headlines arrive.
- **Browser Desktop Notifications**: Native system notifications pop up when new high-impact market news breaks, even if the browser tab is in the background.
- **Live Filtering & Search**: Instant filter tabs and fuzzy keyword search across titles and news sources.
- **Auto-Refresh**: Live polling (every 15s, 30s, 1m, or 2m) with progress bar and countdown.
- **Multi-Source Aggregation**: Pulls news from FinancialJuice, Reuters, Forex Factory, Bloomberg, CNBC, and Moneycontrol.
- **Two Deployment Modes**:
  1. **Local Web App & Terminal**: Run `python server.py` to use on `http://localhost:8000`.
  2. **Vercel Serverless & Cron**: Deploy to Vercel for zero-maintenance hosting and optional 5-minute Telegram bot notifications.

---

## 🚀 Running Locally

### Option 1: Live Web Dashboard (Recommended)
```bash
python server.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

### Option 2: Desktop Script with Terminal / System Notifications
```bash
pip install plyer
python gold_forex_alert.py
```

---

## 🌐 Deploying to Vercel

1. Commit your files to your GitHub repository:
   ```bash
   git add .
   git commit -m "Add real-time web UI and news API"
   git push origin main
   ```
2. In your Vercel Dashboard, your project will automatically trigger a new deployment.
3. Once deployed, open your Vercel URL (e.g. `https://newsalert-lake.vercel.app/`). The terminal interface will load immediately and stream live alerts!

### Optional: Background Telegram Alerts via Vercel Cron
If you want automated Telegram notifications sent every 5 minutes even when no browser is open:
1. Connect a Vercel KV store to your project.
2. In Vercel Project Settings > Environment Variables, add:
   - `TELEGRAM_BOT_TOKEN`: From `@BotFather`
   - `TELEGRAM_CHAT_ID`: Your Telegram chat ID
   - `CRON_SECRET`: Random secret string
   - `KV_REST_API_URL`: From Vercel KV
   - `KV_REST_API_TOKEN`: From Vercel KV
