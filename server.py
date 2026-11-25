#!/usr/bin/env python3
"""
Local development server for Gold & Forex Alert Terminal.
Serves the web UI and handles /api/news locally.

Run:
    python server.py
Then open http://localhost:8000 in your browser.
"""

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api.news import get_latest_news


class LocalDevHandler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        # Route /api/news
        if self.path.startswith("/api/news"):
            try:
                data = get_latest_news()
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
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
            return

        # Default route to index.html
        if self.path == "/" or not os.path.exists(self.translate_path(self.path)):
            self.path = "/index.html"

        return super().do_GET()


def main():
    port = 8000
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, LocalDevHandler)
    print("=" * 60)
    print(f"  Gold & Forex Alert Terminal running locally")
    print(f"  Open in browser: http://localhost:{port}")
    print("  Press Ctrl+C to stop the server")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    main()
