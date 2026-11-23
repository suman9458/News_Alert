# Gold & Forex Alert

A lightweight Python alert for gold and forex news. It can run locally with
desktop notifications, or on Vercel as a five-minute Telegram alert service.

## Run

```bash
pip install plyer
python gold_forex_alert.py
```

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the script only for local
use. Do not commit real credentials.

Stop the alert with `Ctrl+C`.

## Vercel Telegram deployment

The Vercel deployment exposes a protected `/api/cron` endpoint and calls it
every five minutes. Before deploying, create a Vercel KV store and add these
Production environment variables in Vercel:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CRON_SECRET` (a long random value)
- `KV_REST_API_URL`
- `KV_REST_API_TOKEN`

The KV values are provided when you connect the Vercel KV store. The first
scheduled run records existing headlines without sending them; subsequent runs
send only new matching headlines to Telegram.
