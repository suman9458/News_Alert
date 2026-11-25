#!/usr/bin/env python3
"""
Vercel Serverless Function: GET /api/calendar
Fetches, caches, and parses economic calendar data (Forex Factory)
Returns structured upcoming economic data:
- Date & Time
- Country & Currency (USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF, CNY)
- News/Event Name (Fed rate, CPI, NFP, GDP, PMI, Retail Sales)
- Impact (High, Medium, Low)
- Forecast & Previous data
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
import json
import time
import urllib.request
import xml.etree.ElementTree as ET

CACHE_TTL_SECONDS = 900  # 15 minutes cache to prevent rate-limiting
CALENDAR_WINDOW_DAYS = 5
CALENDAR_FEED_URLS = [
    'https://nfs.faireconomy.media/ff_calendar_thisweek.json',
    # Use the following-week feed when the upstream provides it.
    'https://nfs.faireconomy.media/ff_calendar_nextweek.json',
]

_cached_calendar = None
_cached_time = 0

CURRENCY_TO_COUNTRY = {
    'USD': {'code': 'US', 'name': 'United States', 'flag': '/flags/us.png', 'cdn': 'https://flagcdn.com/w40/us.png', 'emoji': 'ðŸ‡ºðŸ‡¸'},
    'EUR': {'code': 'EU', 'name': 'Eurozone', 'flag': '/flags/eu.png', 'cdn': 'https://flagcdn.com/w40/eu.png', 'emoji': 'ðŸ‡ªðŸ‡º'},
    'GBP': {'code': 'UK', 'name': 'United Kingdom', 'flag': '/flags/gb.png', 'cdn': 'https://flagcdn.com/w40/gb.png', 'emoji': 'ðŸ‡¬ðŸ‡§'},
    'JPY': {'code': 'JP', 'name': 'Japan', 'flag': '/flags/jp.png', 'cdn': 'https://flagcdn.com/w40/jp.png', 'emoji': 'ðŸ‡¯ðŸ‡µ'},
    'AUD': {'code': 'AU', 'name': 'Australia', 'flag': '/flags/au.png', 'cdn': 'https://flagcdn.com/w40/au.png', 'emoji': 'ðŸ‡¦ðŸ‡º'},
    'NZD': {'code': 'NZ', 'name': 'New Zealand', 'flag': '/flags/nz.png', 'cdn': 'https://flagcdn.com/w40/nz.png', 'emoji': 'ðŸ‡³ðŸ‡¿'},
    'CAD': {'code': 'CA', 'name': 'Canada', 'flag': '/flags/ca.png', 'cdn': 'https://flagcdn.com/w40/ca.png', 'emoji': 'ðŸ‡¨ðŸ‡¦'},
    'CHF': {'code': 'CH', 'name': 'Switzerland', 'flag': '/flags/ch.png', 'cdn': 'https://flagcdn.com/w40/ch.png', 'emoji': 'ðŸ‡¨ðŸ‡­'},
    'CNY': {'code': 'CN', 'name': 'China', 'flag': '/flags/cn.png', 'cdn': 'https://flagcdn.com/w40/cn.png', 'emoji': 'ðŸ‡¨ðŸ‡³'},
}

def parse_event(idx, raw_ev):
    title = raw_ev.get('title', '').strip()
    currency = raw_ev.get('country', '').strip().upper()
    impact = raw_ev.get('impact', 'Low').strip().capitalize()
    forecast = raw_ev.get('forecast', '').strip()
    previous = raw_ev.get('previous', '').strip()

    date_raw = raw_ev.get('date', '')
    time_raw = raw_ev.get('time', '')
    timestamp = 0
    date_formatted = ''
    date_key = ''
    time_display = time_raw

    try:
        if 'T' in date_raw:
            dt = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamp = int(dt.timestamp())
            date_formatted = dt.strftime('%A, %b %d, %Y')
            date_key = dt.strftime('%Y-%m-%d')
            time_display = dt.strftime('%I:%M %p')
        elif date_raw:
            full_str = f"{date_raw} {time_raw}".strip()
            dt = None
            for date_format in ('%m-%d-%Y %I:%M%p', '%m-%d-%Y %I:%M %p'):
                try:
                    dt = datetime.strptime(full_str, date_format).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            if dt is None:
                raise ValueError(f'Unsupported calendar date: {full_str}')
            timestamp = int(dt.timestamp())
            date_formatted = dt.strftime('%A, %b %d, %Y')
            date_key = dt.strftime('%Y-%m-%d')
            time_display = dt.strftime('%I:%M %p')
    except Exception:
        date_formatted = date_raw
        date_key = date_raw

    c_info = CURRENCY_TO_COUNTRY.get(currency, {
        'code': currency,
        'name': currency,
        'flag': '',
        'cdn': '',
        'emoji': 'ðŸŒ'
    })

    return {
        'id': f"cal_{idx}_{timestamp}_{currency}",
        'title': title,
        'currency': currency,
        'country': c_info['code'],
        'country_name': c_info['name'],
        'country_flag': c_info['flag'],
        'flag_cdn': c_info['cdn'],
        'flag_emoji': c_info['emoji'],
        'impact': impact if impact in ['High', 'Medium', 'Low'] else 'Low',
        'forecast': forecast or '-',
        'previous': previous or '-',
        'date_raw': date_raw,
        'date_formatted': date_formatted or 'Upcoming',
        'date_key': date_key or 'upcoming',
        'time': time_display or 'Tentative',
        'timestamp': timestamp,
        'source': 'Forex Factory',
    }

def fetch_feed(url, allow_xml=True):
    raw_events = []
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        res = urllib.request.urlopen(req, timeout=5)
        if res.status == 200:
            raw_events = json.loads(res.read().decode('utf-8'))
    except Exception:
        pass

    if not raw_events and allow_xml:
        try:
            xml_url = url.rsplit('.', 1)[0] + '.xml'
            req = urllib.request.Request(
                xml_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            res = urllib.request.urlopen(req, timeout=5)
            if res.status == 200:
                root = ET.fromstring(res.read().decode('windows-1252', errors='replace'))
                for ev in root.findall('event'):
                    raw_events.append({
                        'title': ev.findtext('title', '').strip(),
                        'country': ev.findtext('country', '').strip(),
                        'date': ev.findtext('date', '').strip(),
                        'time': ev.findtext('time', '').strip(),
                        'impact': ev.findtext('impact', '').strip(),
                        'forecast': ev.findtext('forecast', '').strip(),
                        'previous': ev.findtext('previous', '').strip(),
                    })
        except Exception:
            pass

    return raw_events


def fetch_from_remote():
    raw_events = []
    for feed_index, feed_url in enumerate(CALENDAR_FEED_URLS):
        # Keep the normal feed's XML fallback, but avoid extra upstream
        # requests when probing the optional following-week JSON feed.
        raw_events.extend(fetch_feed(feed_url, allow_xml=feed_index == 0))

    if not raw_events:
        # Load seed fallback if remote is rate-limiting
        try:
            import os
            seed_path = os.path.join(os.path.dirname(__file__), 'calendar_seed.json')
            if os.path.exists(seed_path):
                with open(seed_path, 'r', encoding='utf-8') as f:
                    raw_events = json.load(f)
        except Exception:
            pass

    if not raw_events:
        return []

    parsed = [parse_event(idx, ev) for idx, ev in enumerate(raw_events)]
    # Filter out empty or holiday titles without currency
    parsed = [p for p in parsed if p['title'] and p['currency']]
    unique = {}
    for event in parsed:
        key = (event['title'], event['currency'], event['timestamp'])
        unique[key] = event
    parsed = list(unique.values())

    now = time.time()
    window_end = now + CALENDAR_WINDOW_DAYS * 24 * 60 * 60
    parsed = [
        event for event in parsed
        if event['timestamp'] and now <= event['timestamp'] <= window_end
    ]
    parsed.sort(key=lambda x: x['timestamp'])
    return parsed

def get_calendar():
    global _cached_calendar, _cached_time
    now = time.time()

    if _cached_calendar is not None and (now - _cached_time) < CACHE_TTL_SECONDS:
        return _cached_calendar

    events = fetch_from_remote()

    # If fetch succeeded, update cache
    if events:
        result = {
            "status": "ok",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": len(events),
            "window_days": CALENDAR_WINDOW_DAYS,
            "events": events
        }
        _cached_calendar = result
        _cached_time = now
        return result

    # If remote failed but we have stale cache, return stale cache
    if _cached_calendar is not None:
        return _cached_calendar

    # Fallback to empty ok response if initial call failed
    return {
        "status": "ok",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": 0,
        "window_days": CALENDAR_WINDOW_DAYS,
        "events": []
    }

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            data = get_calendar()
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

