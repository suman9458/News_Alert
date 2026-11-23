# Gold & Forex Alert

A lightweight Python script that checks gold and forex news feeds every five
minutes and sends desktop notifications. Telegram notifications are optional.

## Run

```bash
pip install plyer
python gold_forex_alert.py
```

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the script only for local
use. Do not commit real credentials.

Stop the alert with `Ctrl+C`.
