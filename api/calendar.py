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

from datetime import datetime
from http.server import BaseHTTPRequestHandler
import json
import time
import urllib.request
import xml.etree.ElementTree as ET

CACHE_TTL_SECONDS = 900  # 15 minutes cache to prevent rate-limiting

_cached_calendar = None
_cached_time = 0

CURRENCY_TO_COUNTRY = {
    'USD': {'code': 'US', 'name': 'United States', 'flag': '/flags/us.png', 'cdn': 'https://flagcdn.com/w40/us.png', 'emoji': '🇺🇸'},
    'EUR': {'code': 'EU', 'name': 'Eurozone', 'flag': '/flags/eu.png', 'cdn': 'https://flagcdn.com/w40/eu.png', 'emoji': '🇪🇺'},
    'GBP': {'code': 'UK', 'name': 'United Kingdom', 'flag': '/flags/gb.png', 'cdn': 'https://flagcdn.com/w40/gb.png', 'emoji': '🇬🇧'},
    'JPY': {'code': 'JP', 'name': 'Japan', 'flag': '/flags/jp.png', 'cdn': 'https://flagcdn.com/w40/jp.png', 'emoji': '🇯🇵'},
    'AUD': {'code': 'AU', 'name': 'Australia', 'flag': '/flags/au.png', 'cdn': 'https://flagcdn.com/w40/au.png', 'emoji': '🇦🇺'},
    'NZD': {'code': 'NZ', 'name': 'New Zealand', 'flag': '/flags/nz.png', 'cdn': 'https://flagcdn.com/w40/nz.png', 'emoji': '🇳🇿'},
    'CAD': {'code': 'CA', 'name': 'Canada', 'flag': '/flags/ca.png', 'cdn': 'https://flagcdn.com/w40/ca.png', 'emoji': '🇨🇦'},
    'CHF': {'code': 'CH', 'name': 'Switzerland', 'flag': '/flags/ch.png', 'cdn': 'https://flagcdn.com/w40/ch.png', 'emoji': '🇨🇭'},
    'CNY': {'code': 'CN', 'name': 'China', 'flag': '/flags/cn.png', 'cdn': 'https://flagcdn.com/w40/cn.png', 'emoji': '🇨🇳'},
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
            dt = datetime.fromisoformat(date_raw)
            timestamp = int(dt.timestamp())
            date_formatted = dt.strftime('%A, %b %d, %Y')
            date_key = dt.strftime('%Y-%m-%d')
            time_display = dt.strftime('%I:%M %p')
        elif date_raw:
            full_str = f"{date_raw} {time_raw}".strip()
            dt = datetime.strptime(full_str, '%m-%d-%Y %I:%M%p')
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
        'emoji': '🌐'
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

def fetch_from_remote():
    raw_events = []
    # 1. Try JSON
    try:
        req = urllib.request.Request(
            'https://nfs.faireconomy.media/ff_calendar_thisweek.json',
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        res = urllib.request.urlopen(req, timeout=5)
        if res.status == 200:
            raw_events = json.loads(res.read().decode('utf-8'))
    except Exception:
        pass

    # 2. Try XML fallback
    if not raw_events:
        try:
            req = urllib.request.Request(
                'https://nfs.faireconomy.media/ff_calendar_thisweek.xml',
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

def load_seed_events():
    try:
        import os
        seed_path = os.path.join(os.path.dirname(__file__), 'calendar_seed.json')
        if os.path.exists(seed_path):
            with open(seed_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []

def get_calendar():
    global _cached_calendar, _cached_time
    now = time.time()

    if _cached_calendar is not None and (now - _cached_time) < CACHE_TTL_SECONDS:
        return _cached_calendar

    remote_raw = fetch_from_remote()
    seed_raw = load_seed_events()

    remote_parsed = [parse_event(f"rem_{i}", ev) for i, ev in enumerate(remote_raw)]
    remote_parsed = [p for p in remote_parsed if p['title'] and p['currency']]

    seed_parsed = [parse_event(f"seed_{i}", ev) for i, ev in enumerate(seed_raw)]
    seed_parsed = [p for p in seed_parsed if p['title'] and p['currency']]

    # Merge: remote events take precedence, seed events add upcoming days
    merged = []
    seen = set()

    for p in remote_parsed:
        k = (p['title'].lower().strip(), p['date_key'], p['currency'])
        if k not in seen:
            seen.add(k)
            merged.append(p)

    for p in seed_parsed:
        k = (p['title'].lower().strip(), p['date_key'], p['currency'])
        if k not in seen:
            seen.add(k)
            merged.append(p)

    merged.sort(key=lambda x: x['timestamp'])

    if merged:
        result = {
            "status": "ok",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": len(merged),
            "events": merged
        }
        _cached_calendar = result
        _cached_time = now
        return result

    if _cached_calendar is not None:
        return _cached_calendar

    return {
        "status": "ok",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": 0,
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
