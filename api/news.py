#!/usr/bin/env python3
"""
Vercel Serverless Function: GET /api/news
Fetches, cleans, filters, and categorizes real-time Gold, Forex, and Macro news headlines.
Includes concurrent multi-source fetching and in-memory caching.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import email.utils
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler

# Direct RSS Feeds
DIRECT_FEEDS = [
    ("FXStreet", "https://www.fxstreet.com/rss/news"),
    ("Investing.com", "https://www.investing.com/rss/news_1.rss"),
    ("Investing.com", "https://www.investing.com/rss/news_11.rss"),
    ("FinancialJuice", "https://www.financialjuice.com/feed.ashx?xy=rss"),
]

# Google News search queries
GOOGLE_NEWS_QUERIES = [
    ("Gold Wire", "gold price OR xauusd OR bullion OR silver when:1d"),
    ("Forex Wire", "forex OR eurusd OR \"us dollar\" OR dxy OR gbpusd OR usdjpy when:1d"),
    ("Fed & Central Banks", "\"federal reserve\" OR fomc OR powell OR \"interest rate\" OR \"rate cut\" OR inflation when:1d"),
    ("Reuters", "gold OR forex OR dollar site:reuters.com when:1d"),
    ("Forex Factory", "forex site:forexfactory.com when:1d"),
    ("Moneycontrol", "gold OR forex OR dollar site:moneycontrol.com when:1d"),
    ("FinancialJuice", "site:financialjuice.com when:1d"),
]

# Keywords
RE_GOLD = re.compile(
    r"\b(gold|xau|xauusd|bullion|precious metals?|silver|spot gold|gold futures)\b",
    re.IGNORECASE,
)
RE_FED = re.compile(
    r"\b(fed|federal reserve|fomc|powell|interest rates?|rate cut|rate hike|inflation|cpi|ppi|pmi|gdp|non-?farm|payrolls|warsh|central bank|central banks|ecb|lagarde|boe|bailey|boj|rba)\b",
    re.IGNORECASE,
)
RE_FOREX = re.compile(
    r"\b(forex|fx|eur/?usd|gbp/?usd|usd/?jpy|aud/?usd|usd/?chf|usd/?cad|nzd/?usd|dxy|us dollar|greenback|currencies|currency|yields|treasury|bonds)\b",
    re.IGNORECASE,
)

# Broad market filter: captures any news relevant to Gold, Currencies, Central Banks & Macro
KEYWORDS_FILTER = re.compile(
    r"\b(gold|xau|xauusd|bullion|silver|forex|fx|eur/?usd|gbp/?usd|usd/?jpy|aud/?usd|usd/?chf|usd/?cad|dxy|fed|fomc|powell|dollar|usd|inflation|cpi|rate cut|rate hike|interest rate|central bank|ecb|boe|boj|rba|yields|treasury|economy|market wrap)\b",
    re.IGNORECASE,
)

CACHE_TTL_SECONDS = 20
_cached_data = None
_cached_time = 0


def google_news_url(query):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def get_all_feed_configs():
    feeds = list(DIRECT_FEEDS)
    for name, query in GOOGLE_NEWS_QUERIES:
        feeds.append((name, google_news_url(query)))
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
    return "Market Wire"


def clean_title_and_source(raw_title, default_source):
    clean = raw_title.strip()
    source = default_source

    if clean.lower().startswith("financialjuice:"):
        clean = clean[15:].strip()
        source = "FinancialJuice"

    parts = re.split(r"\s+-\s+([^-]+)$", clean)
    if len(parts) > 1 and parts[1].strip():
        extracted_source = parts[1].strip()
        if len(extracted_source) < 25:
            source = extracted_source
            clean = parts[0].strip()

    return clean, source


def fetch_feed(source_label, url):
    items = []
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        content = resp.read()
        root = ET.fromstring(content)

    is_direct_financial_feed = source_label in ("FXStreet", "FinancialJuice", "Investing.com")

    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or raw_title).strip()
        pub_date_str = (item.findtext("pubDate") or "").strip()

        if not raw_title:
            continue

        clean_title, source = clean_title_and_source(raw_title, source_label)

        # For direct market feeds, allow all items; for general search, apply keyword check
        if not is_direct_financial_feed and not KEYWORDS_FILTER.search(raw_title):
            continue

        epoch, formatted_date = parse_pub_date(pub_date_str)
        category = determine_category(raw_title)

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

    if _cached_data is not None and (now - _cached_time) < CACHE_TTL_SECONDS:
        return _cached_data

    feed_configs = get_all_feed_configs()
    collected = []
    seen_titles = set()

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_source = {
            executor.submit(fetch_feed, source_label, url): source_label
            for source_label, url in feed_configs
        }
        for future in as_completed(future_to_source):
            try:
                feed_items = future.result()
                for item in feed_items:
                    normalized_key = item["title"].lower()
                    if normalized_key not in seen_titles:
                        seen_titles.add(normalized_key)
                        collected.append(item)
            except Exception:
                continue

    # Sort descending by timestamp (newest first)
    collected.sort(key=lambda x: x["timestamp"], reverse=True)

    result = {
        "status": "ok",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(collected),
        "news": collected[:200],  # Return up to 200 comprehensive headlines
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
