#!/usr/bin/env python3
"""
Vercel Serverless Function: GET /api/news
Fetches, cleans, filters, and categorizes real-time Gold & Forex news headlines.
Includes an in-memory cache to prevent feed throttling and ensure fast response times.
"""

import email.utils
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler

# Sites to watch via Google News RSS
GOOGLE_NEWS_SITES = [
    "reuters.com",
    "forexfactory.com",
    "moneycontrol.com",
    "financialjuice.com",
    "bloomberg.com",
    "cnbc.com",
]

GOOGLE_NEWS_TOPICS = ["gold", "forex", "fed"]

DIRECT_FEEDS = [
    ("FinancialJuice", "https://www.financialjuice.com/feed.ashx?xy=rss"),
]

# Keywords
RE_GOLD = re.compile(r"\b(gold|xau|xauusd|bullion|precious metals?|silver)\b", re.IGNORECASE)
RE_FED = re.compile(r"\b(fed|federal reserve|fomc|powell|interest rates?|rate cut|rate hike|inflation|cpi|central bank)\b", re.IGNORECASE)
RE_FOREX = re.compile(r"\b(forex|fx|eur/usd|eurusd|gbp/usd|usd/jpy|dxy|us dollar|greenback|currencies|currency|yields)\b", re.IGNORECASE)

KEYWORDS_FILTER = re.compile(
    r"\b(gold|xau|xauusd|bullion|silver|forex|fx|eur/?usd|gbp/?usd|usd/?jpy|dxy|fed|fomc|powell|dollar|usd|inflation|rate cut|rate hike)\b",
    re.IGNORECASE,
)

# In-memory cache for Vercel warm instances
CACHE_TTL_SECONDS = 40
_cached_data = None
_cached_time = 0


def google_news_url(site, topic):
    q = urllib.parse.quote(f"{topic} site:{site} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def get_all_feed_configs():
    feeds = list(DIRECT_FEEDS)
    for site in GOOGLE_NEWS_SITES:
        # Determine source name from domain
        name = site.split(".")[0].capitalize()
        if site == "forexfactory.com":
            name = "Forex Factory"
        elif site == "financialjuice.com":
            name = "FinancialJuice"
        elif site == "moneycontrol.com":
            name = "Moneycontrol"
        elif site == "bloomberg.com":
            name = "Bloomberg"
        elif site == "cnbc.com":
            name = "CNBC"
        elif site == "reuters.com":
            name = "Reuters"

        for topic in GOOGLE_NEWS_TOPICS:
            feeds.append((name, google_news_url(site, topic)))
    return feeds


def parse_pub_date(date_str):
    if not date_str:
        return int(time.time()), ""
    try:
        parsed_tuple = email.utils.parsedate_tz(date_str)
        if parsed_tuple:
            timestamp = email.utils.mktime_tz(parsed_tuple)
            return int(timestamp), date_str
    except Exception:
        pass
    return int(time.time()), date_str


def determine_category(title):
    if RE_GOLD.search(title):
        return "Gold"
    if RE_FED.search(title):
        return "Fed & Economy"
    if RE_FOREX.search(title):
        return "Forex"
    return "Market"


def clean_title_and_source(raw_title, default_source):
    clean = raw_title.strip()
    source = default_source

    # Clean FinancialJuice prefix
    if clean.lower().startswith("financialjuice:"):
        clean = clean[15:].strip()
        source = "FinancialJuice"

    # Extract source from title suffix " - Reuters"
    parts = re.split(r"\s+-\s+([^-]+)$", clean)
    if len(parts) > 1 and parts[1].strip():
        extracted_source = parts[1].strip()
        if len(extracted_source) < 25:  # avoid false split on long sentences
            source = extracted_source
            clean = parts[0].strip()

    return clean, source


def fetch_feed(source_label, url):
    items = []
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        content = resp.read()
        root = ET.fromstring(content)

    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or raw_title).strip()
        pub_date_str = (item.findtext("pubDate") or "").strip()

        if not raw_title:
            continue

        clean_title, source = clean_title_and_source(raw_title, source_label)

        # Keyword filter check
        if not KEYWORDS_FILTER.search(raw_title):
            continue

        epoch, formatted_date = parse_pub_date(pub_date_str)
        category = determine_category(raw_title)

        # Generate a stable short ID
        item_id = hashlib.md5(f"{clean_title.lower()}-{source.lower()}".encode()).hexdigest()[:12]

        items.append({
            "id": item_id,
            "title": clean_title,
            "raw_title": raw_title,
            "link": link,
            "source": source,
            "category": category,
            "pubDate": formatted_date,
            "timestamp": epoch,
        })
    return items


def get_latest_news():
    global _cached_data, _cached_time
    now = time.time()

    # Serve cached data if still valid
    if _cached_data is not None and (now - _cached_time) < CACHE_TTL_SECONDS:
        return _cached_data

    feed_configs = get_all_feed_configs()
    collected = []
    seen_titles = set()

    for source_label, url in feed_configs:
        try:
            feed_items = fetch_feed(source_label, url)
            for item in feed_items:
                normalized_key = item["title"].lower()
                # Deduplicate similar headlines
                if normalized_key not in seen_titles:
                    seen_titles.add(normalized_key)
                    collected.append(item)
        except Exception:
            # Continue fetching other feeds if one times out or fails
            continue

    # Sort descending by timestamp
    collected.sort(key=lambda x: x["timestamp"], reverse=True)

    result = {
        "status": "ok",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(collected),
        "news": collected[:60],  # Return up to 60 top headlines
    }

    _cached_data = result
    _cached_time = now
    return result


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            data = get_latest_news()
            payload = json.dumps(data).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", f"public, max-age={CACHE_TTL_SECONDS}")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            err_payload = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(err_payload)))
            self.end_headers()
            self.wfile.write(err_payload)

    def log_message(self, format, *args):
        return
