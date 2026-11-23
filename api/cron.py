"""Vercel Cron endpoint for Gold & Forex Telegram alerts.

Required Vercel environment variables:
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CRON_SECRET,
KV_REST_API_URL, KV_REST_API_TOKEN.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler


GOOGLE_NEWS_SITES = [
    "reuters.com",
    "moneycontrol.com",
    "forexfactory.com",
    "financialjuice.com",
]
GOOGLE_NEWS_TOPICS = ["gold", "forex"]
DIRECT_FEEDS = ["https://www.financialjuice.com/feed.ashx?xy=rss"]
KEYWORDS = [
    "gold", "xau", "xauusd", "bullion", "forex", "fx", "eur/usd",
    "eurusd", "gbp/usd", "usd/jpy", "dxy", "fed", "dollar", "usd",
]
SEEN_SET = "news-alert:seen"
INITIALIZED_KEY = "news-alert:initialized"
MAX_ALERTS_PER_RUN = 10

pattern = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(k) for k in KEYWORDS) + r")(?![a-z])",
    re.IGNORECASE,
)


def google_news_url(site, topic):
    query = urllib.parse.quote(f"{topic} site:{site} when:1d")
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def feeds():
    return DIRECT_FEEDS + [
        google_news_url(site, topic)
        for site in GOOGLE_NEWS_SITES
        for topic in GOOGLE_NEWS_TOPICS
    ]


def fetch_items(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=6) as response:
        root = ET.fromstring(response.read())

    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        if title and guid:
            items.append((title, link, guid))
    return items


def redis_command(*arguments):
    url = os.environ["KV_REST_API_URL"].rstrip("/")
    token = os.environ["KV_REST_API_TOKEN"]
    request = urllib.request.Request(
        url,
        data=json.dumps(list(arguments)).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read()).get("result")


def telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read()).get("ok", False)


def collect_items():
    all_items = []
    failed_feeds = 0
    for url in feeds():
        try:
            all_items.extend(fetch_items(url))
        except Exception:
            failed_feeds += 1
    return all_items, failed_feeds


def run_alerts():
    items, failed_feeds = collect_items()
    unique_items = {}
    for title, link, guid in items:
        unique_items.setdefault(guid, (title, link))

    seen = set(redis_command("SMEMBERS", SEEN_SET) or [])
    initialized = redis_command("GET", INITIALIZED_KEY) == "1"
    all_guids = list(unique_items)

    if not initialized:
        if all_guids:
            redis_command("SADD", SEEN_SET, *all_guids)
        redis_command("SET", INITIALIZED_KEY, "1")
        return {"status": "initialized", "items_scanned": len(all_guids), "failed_feeds": failed_feeds}

    new_items = [
        (title, link, guid)
        for guid, (title, link) in unique_items.items()
        if guid not in seen and pattern.search(title)
    ]
    if all_guids:
        redis_command("SADD", SEEN_SET, *all_guids)

    sent = 0
    for title, link, _ in new_items[:MAX_ALERTS_PER_RUN]:
        headline = re.sub(r"\s+-\s+[^-]+$", "", title)
        if telegram(f"{headline}\n{link}"):
            sent += 1

    return {
        "status": "ok",
        "items_scanned": len(all_guids),
        "matching_new_items": len(new_items),
        "sent": sent,
        "failed_feeds": failed_feeds,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected_secret = os.environ.get("CRON_SECRET")
        authorization = self.headers.get("Authorization", "")
        if not expected_secret or authorization != f"Bearer {expected_secret}":
            self.respond(401, {"error": "Unauthorized"})
            return

        required = [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "KV_REST_API_URL",
            "KV_REST_API_TOKEN",
        ]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            self.respond(500, {"error": "Missing environment variables", "variables": missing})
            return

        try:
            self.respond(200, run_alerts())
        except Exception as error:
            self.respond(500, {"error": "Alert run failed", "detail": str(error)})

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return
