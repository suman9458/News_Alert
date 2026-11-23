#!/usr/bin/env python3
"""
Gold & Forex news alert for: Moneycontrol, Forex Factory, Reuters, FinancialJuice.
Checks every 5 minutes and notifies you about NEW headlines that match your keywords.

Setup:
    pip install plyer          # desktop notifications (optional, falls back to a beep)
    python gold_forex_alert.py

Stop with Ctrl+C. Leave it running, or run it as a background/scheduled task.

HOW EACH SITE IS COVERED
- Reuters: has NO public RSS feed (discontinued in 2020), so we read Google News
  results limited to reuters.com.
- Forex Factory: its old RSS feeds are reported unreliable, so we use Google News
  limited to forexfactory.com.
- Moneycontrol: Google News limited to moneycontrol.com, plus a direct feed
  (verify the URL opens in your browser).
- FinancialJuice: direct RSS feed (verify the URL), plus a Google News fallback.

NOTE: Google News can lag the original site by minutes to hours. For the fastest
alerts, the direct feeds (FinancialJuice especially) are better.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# ---------------- SETTINGS ----------------
CHECK_EVERY_SECONDS = 300  # 5 minutes

# Sites to watch through Google News (works even when a site has no RSS)
GOOGLE_NEWS_SITES = [
    "reuters.com",
    "moneycontrol.com",
    "forexfactory.com",
    "financialjuice.com",
]
GOOGLE_NEWS_TOPICS = ["gold", "forex"]

# Direct feeds. Unverified ones are marked: open each in a browser first,
# and delete any that don't load.
DIRECT_FEEDS = [
    "https://www.financialjuice.com/feed.ashx?xy=rss",   # FinancialJuice (verify)
]

# A headline must contain one of these words to trigger an alert.
# Short/broad words like "fed" or "usd" will alert often; remove if too noisy.
KEYWORDS = [
    "gold", "xau", "xauusd", "bullion",
    "forex", "fx", "eur/usd", "eurusd", "gbp/usd", "usd/jpy", "dxy",
    "fed", "dollar", "usd",
]

# Optional Telegram alerts (leave empty to skip)
TELEGRAM_BOT_TOKEN = ""   # from @BotFather
TELEGRAM_CHAT_ID = ""     # your chat id

SEEN_FILE = "seen_news.json"
# ------------------------------------------


def google_news_url(site, topic):
    q = urllib.parse.quote(f"{topic} site:{site} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def all_feeds():
    feeds = list(DIRECT_FEEDS)
    for site in GOOGLE_NEWS_SITES:
        for topic in GOOGLE_NEWS_TOPICS:
            feeds.append(google_news_url(site, topic))
    return feeds


pattern = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(k) for k in KEYWORDS) + r")(?![a-z])",
    re.IGNORECASE,
)

warned_feeds = set()


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-8000:], f)


def fetch_items(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        if title:
            items.append((title, link, guid))
    return items


def notify_desktop(title, message):
    try:
        from plyer import notification
        notification.notify(title=title, message=message[:250], timeout=10)
    except Exception:
        print("\a", end="")  # terminal beep fallback


def notify_telegram(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        data = urllib.parse.urlencode(
            {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        ).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=data,
            timeout=20,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


def check_once(feeds, seen, first_run):
    alerted_titles = set()  # avoid double alerts when feeds overlap
    for url in feeds:
        try:
            items = fetch_items(url)
        except Exception as e:
            if url not in warned_feeds:
                print(f"[warn] feed failed: {url[:80]}... ({e})")
                warned_feeds.add(url)
            continue
        for title, link, guid in items:
            if guid in seen:
                continue
            seen.add(guid)
            if first_run:
                continue  # don't alert on old headlines at startup
            headline = re.sub(r"\s+-\s+[^-]+$", "", title)
            key = headline.lower()
            if key in alerted_titles or not pattern.search(headline):
                continue
            alerted_titles.add(key)
            print(f"[{time.strftime('%H:%M')}] [NEWS] {title}\n       {link}")
            notify_desktop("Gold/Forex news", title)
            notify_telegram(f"{title}\n{link}")


def main():
    feeds = all_feeds()
    seen = load_seen()
    first_run = not seen
    print(f"Watching {len(feeds)} feeds every {CHECK_EVERY_SECONDS // 60} min. Ctrl+C to stop.")
    while True:
        check_once(feeds, seen, first_run)
        first_run = False
        save_seen(seen)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
