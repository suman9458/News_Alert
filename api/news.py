#!/usr/bin/env python3
"""
Vercel Serverless Function: GET /api/news
Exclusively fetches, cleans, filters, and categorizes news headlines from 25 approved sources:
1. Reuters, 2. Bloomberg, 3. CNBC, 4. Financial Times, 5. TradingView
6. FXStreet, 7. ForexLive, 8. DailyFX, 9. Forex Factory, 10. Investing.com
11. CoinDesk, 12. The Block, 13. Cointelegraph, 14. Decrypt, 15. CoinGecko, 16. CoinMarketCap, 17. Glassnode
18. Kitco, 19. World Gold Council, 20. LBMA, 21. MCX
22. Federal Reserve, 23. ECB, 24. RBI, 25. BLS

Includes High / Medium / Low impact classification and Country-wise economic tagging.
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

def _gnews_url(q):
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"

# The 25 specific sources requested by the user
CURATED_FEED_CONFIGS = [
    # General (Forex, Crypto, Gold, Macro)
    ("Reuters", _gnews_url("site:reuters.com (gold OR forex OR dollar OR crypto OR fed) when:2d")),
    ("Bloomberg", _gnews_url("site:bloomberg.com (gold OR forex OR dollar OR crypto OR fed) when:2d")),
    ("CNBC", _gnews_url("site:cnbc.com (gold OR currencies OR dollar OR crypto OR fed) when:2d")),
    ("Financial Times", _gnews_url("site:ft.com (gold OR forex OR dollar OR crypto OR fed) when:2d")),
    ("TradingView", _gnews_url("site:tradingview.com/news when:3d")),

    # Forex
    ("FXStreet", "https://www.fxstreet.com/rss/news"),
    ("ForexLive", _gnews_url("site:forexlive.com OR \"ForexLive\" OR site:investinglive.com when:3d")),
    ("DailyFX", _gnews_url("(\"DailyFX\" OR site:dailyfx.com OR site:ig.com/dailyfx) when:5d")),
    ("Forex Factory", _gnews_url("site:forexfactory.com/news when:3d")),
    ("Investing.com", "https://www.investing.com/rss/news_1.rss"),

    # Crypto
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CoinGecko", _gnews_url("site:coingecko.com when:3d")),
    ("CoinMarketCap", _gnews_url("site:coinmarketcap.com when:3d")),
    ("Glassnode", _gnews_url("site:glassnode.com when:14d")),

    # Gold
    ("Kitco", _gnews_url("site:kitco.com when:3d")),
    ("World Gold Council", _gnews_url("site:gold.org when:14d")),
    ("LBMA", _gnews_url("site:lbma.org.uk when:14d")),
    ("MCX", _gnews_url("site:mcxindia.com OR \"MCX Gold\" when:7d")),

    # Official Sources (Fed, ECB, RBI, BLS)
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB", _gnews_url("site:ecb.europa.eu when:14d")),
    ("RBI", _gnews_url("site:rbi.org.in when:14d")),
    ("BLS", _gnews_url("site:bls.gov when:14d")),
]

# Canonical source mappings to ensure only allowed sources appear
SOURCE_CANONICAL = {
    "reuters": "Reuters",
    "bloomberg": "Bloomberg",
    "cnbc": "CNBC",
    "financial times": "Financial Times",
    "ft.com": "Financial Times",
    "tradingview": "TradingView",
    "fxstreet": "FXStreet",
    "forexlive": "ForexLive",
    "investinglive": "ForexLive",
    "dailyfx": "DailyFX",
    "forex factory": "Forex Factory",
    "investing.com": "Investing.com",
    "coindesk": "CoinDesk",
    "the block": "The Block",
    "theblock": "The Block",
    "cointelegraph": "Cointelegraph",
    "decrypt": "Decrypt",
    "coingecko": "CoinGecko",
    "coinmarketcap": "CoinMarketCap",
    "glassnode": "Glassnode",
    "kitco": "Kitco",
    "world gold council": "World Gold Council",
    "gold.org": "World Gold Council",
    "lbma": "LBMA",
    "mcx": "MCX",
    "multi commodity exchange": "MCX",
    "federal reserve": "Federal Reserve",
    "fed": "Federal Reserve",
    "federal reserve board": "Federal Reserve",
    "ecb": "ECB",
    "european central bank": "ECB",
    "rbi": "RBI",
    "reserve bank of india": "RBI",
    "bls": "BLS",
    "bureau of labor statistics": "BLS",
}

# Category Classification Patterns
RE_CRYPTO = re.compile(
    r"\b(bitcoin|btc|ethereum|eth|solana|sol|crypto|cryptocurrency|altcoins?|binance|bnb|xrp|ripple|stablecoins?|usdt|usdc|defi|sec|etf|blackrock|coinbase|satoshi|halving|on-chain|blockchain)\b",
    re.IGNORECASE,
)
RE_GOLD = re.compile(
    r"\b(gold|xau|xauusd|bullion|precious metals?|silver|spot gold|gold futures|mcx gold|lbma)\b",
    re.IGNORECASE,
)
RE_FED = re.compile(
    r"\b(fed|federal reserve|fomc|powell|interest rates?|rate cuts?|rate hikes?|inflation|cpi|ppi|pmi|gdp|non-?farm|payrolls|warsh|central banks?|ecb|lagarde|boe|bailey|boj|rba|rbi|bls)\b",
    re.IGNORECASE,
)
RE_FOREX = re.compile(
    r"\b(forex|fx|eur/?usd|gbp/?usd|usd/?jpy|aud/?usd|usd/?chf|usd/?cad|nzd/?usd|dxy|us dollar|greenback|currencies|currency|yields|treasury|bonds)\b",
    re.IGNORECASE,
)

# Impact Classification Regex
RE_HIGH_IMPACT = re.compile(
    r"\b(cpi|inflation|nfp|non-?farm|payrolls|unemployment rate|gdp|core pce|rate cut|rate hike|interest rate decision|fomc statement|fomc decision|powell|fomc|warsh|lagarde|bailey|ueda|record high|all-time high|plunges|surges|spikes|crashes|slumps|selloff|rout|war|missile|attack|sanctions?|tariffs?|emergency|intervention|bailout|etf approval|hack|liquidation|sec lawsuit)\b",
    re.IGNORECASE,
)

RE_MEDIUM_IMPACT = re.compile(
    r"\b(pmi|ppi|retail sales|jobless claims|consumer sentiment|consumer confidence|durable goods|ism|trade balance|trade deficit|fed\'?s|williams|waller|bowman|bostic|kashkari|barkin|daly|musalem|centeno|villeroy|nagel|crude|oil|opec|treasury yields?|10-year yield|bond yields?|dxy|dollar index|us dollar|hike bets|cut bets|whale|accumulation|upgrade|outflows?|inflows?)\b",
    re.IGNORECASE,
)

# Country / Economic Region Classification
COUNTRY_PATTERNS = {
    "US": (
        "🇺🇸",
        "United States",
        re.compile(r"\b(us|usa|united states|fed|federal reserve|fomc|powell|dollar|usd|greenback|dxy|treasury|wall street|warsh|biden|trump|cpi|nfp|payrolls|eur/?usd|gbp/?usd|usd/?jpy|aud/?usd|nzd/?usd|usd/?cad|usd/?chf|bls)\b", re.IGNORECASE)
    ),
    "EU": (
        "🇪🇺",
        "Eurozone",
        re.compile(r"\b(euro|eur|ecb|european central bank|lagarde|eurozone|germany|german|france|french|bund|dax|villeroy|nagel|eur/?usd|eur/?gbp|eur/?jpy|eur/?chf)\b", re.IGNORECASE)
    ),
    "UK": (
        "🇬🇧",
        "United Kingdom",
        re.compile(r"\b(uk|britain|british|bank of england|boe|bailey|pound|sterling|gbp|gilts|ftse|london|gbp/?usd|eur/?gbp|gbp/?jpy|lbma)\b", re.IGNORECASE)
    ),
    "JP": (
        "🇯🇵",
        "Japan",
        re.compile(r"\b(japan|japanese|bank of japan|boj|ueda|yen|jpy|nikkei|tokyo|usd/?jpy|eur/?jpy|gbp/?jpy|aud/?jpy)\b", re.IGNORECASE)
    ),
    "AU": (
        "🇦🇺",
        "Australia",
        re.compile(r"\b(australia|australian|rba|reserve bank of australia|bullock|aussie|aud|asx|sydney|aud/?usd|aud/?jpy|aud/?nzd)\b", re.IGNORECASE)
    ),
    "NZ": (
        "🇳🇿",
        "New Zealand",
        re.compile(r"\b(new zealand|rbnz|reserve bank of new zealand|kiwi|nzd|orr|wellington|nzd/?usd|aud/?nzd)\b", re.IGNORECASE)
    ),
    "CA": (
        "🇨🇦",
        "Canada",
        re.compile(r"\b(canada|canadian|bank of canada|boc|macklem|loonie|cad|usd/?cad)\b", re.IGNORECASE)
    ),
    "CH": (
        "🇨🇭",
        "Switzerland",
        re.compile(r"\b(switzerland|swiss|snb|swiss national bank|franc|chf|usd/?chf|eur/?chf)\b", re.IGNORECASE)
    ),
    "CN": (
        "🇨🇳",
        "China",
        re.compile(r"\b(china|chinese|pboc|people\'?s bank of china|yuan|renminbi|cny|beijing|shanghai)\b", re.IGNORECASE)
    ),
}

CACHE_TTL_SECONDS = 20
_cached_data = None
_cached_time = 0


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


def determine_category(title, source_label):
    if source_label in ("Kitco", "World Gold Council", "LBMA", "MCX"):
        return "Gold"
    if source_label in ("CoinDesk", "The Block", "Cointelegraph", "Decrypt", "CoinGecko", "CoinMarketCap", "Glassnode"):
        return "Crypto"
    if source_label in ("Federal Reserve", "ECB", "RBI", "BLS"):
        return "Fed & Economy"
    if source_label in ("FXStreet", "ForexLive", "DailyFX", "Forex Factory"):
        if RE_GOLD.search(title):
            return "Gold"
        if RE_CRYPTO.search(title):
            return "Crypto"
        return "Forex"

    # General multi-asset sources (Reuters, Bloomberg, CNBC, Financial Times, TradingView, Investing.com)
    if RE_CRYPTO.search(title):
        return "Crypto"
    if RE_GOLD.search(title):
        return "Gold"
    if RE_FED.search(title):
        return "Fed & Economy"
    if RE_FOREX.search(title):
        return "Forex"
    return "Market Wire"


def determine_impact(title):
    if RE_HIGH_IMPACT.search(title):
        return "High"
    if RE_MEDIUM_IMPACT.search(title):
        return "Medium"
    return "Low"


def determine_countries(text):
    matched = []
    primary_code = "GLOBAL"
    primary_flag = "🌍"

    for code, (flag, name, pat) in COUNTRY_PATTERNS.items():
        if pat.search(text):
            matched.append(code)
            if primary_code == "GLOBAL":
                primary_code = code
                primary_flag = flag

    if not matched:
        matched = ["GLOBAL"]

    return matched, primary_code, primary_flag


def clean_title_and_source(raw_title, default_source):
    clean = raw_title.strip()
    source = default_source

    parts = re.split(r"\s+-\s+([^-]+)$", clean)
    if len(parts) > 1 and parts[1].strip():
        extracted = parts[1].strip().lower()
        clean = parts[0].strip()
        for alias, canon in SOURCE_CANONICAL.items():
            if alias in extracted:
                source = canon
                break

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

    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_str = (item.findtext("pubDate") or "").strip()

        if not raw_title:
            continue

        clean_title, source = clean_title_and_source(raw_title, source_label)

        epoch, formatted_date = parse_pub_date(pub_date_str)
        category = determine_category(clean_title, source)
        impact = determine_impact(clean_title)
        countries, primary_code, primary_flag = determine_countries(clean_title)

        item_id = hashlib.md5(f"{clean_title.lower()}-{source.lower()}".encode()).hexdigest()[:12]

        items.append({
            "id": item_id,
            "title": clean_title,
            "raw_title": raw_title,
            "link": link,
            "source": source,
            "category": category,
            "impact": impact,
            "countries": countries,
            "country": primary_code,
            "country_flag": primary_flag,
            "pubDate": formatted_date,
            "timestamp": epoch,
        })
    return items


def get_latest_news():
    global _cached_data, _cached_time
    now = time.time()

    if _cached_data is not None and (now - _cached_time) < CACHE_TTL_SECONDS:
        return _cached_data

    collected = []
    seen_titles = set()

    with ThreadPoolExecutor(max_workers=12) as executor:
        future_to_source = {
            executor.submit(fetch_feed, source_label, url): source_label
            for source_label, url in CURATED_FEED_CONFIGS
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
        "news": collected[:250],
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
