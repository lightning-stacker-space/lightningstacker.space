#!/usr/bin/env python3
"""
LNURL-pay / Lightning Address server for lightningstacker.space
Reads config from environment variables — never hardcode secrets.

Required env vars:
  CLNREST_URL   e.g. https://10.x.x.x:7378
  CLNREST_RUNE  CLNRest rune (lightning-cli createrune)

Optional env vars:
  DOMAIN        default: lightningstacker.space
  PORT          default: 8282
  MIN_SATS      default: 1
  MAX_SATS      default: 10000000
  USERS         comma-separated list, default: hal,propinas,tips
"""

import json
import os
import ssl
import time
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

DOMAIN      = os.environ.get("DOMAIN", "lightningstacker.space")
CLNREST_URL = os.environ["CLNREST_URL"]
RUNE        = os.environ["CLNREST_RUNE"]
PORT        = int(os.environ.get("PORT", 8282))
MIN_SATS    = int(os.environ.get("MIN_SATS", 1))
MAX_SATS    = int(os.environ.get("MAX_SATS", 10_000_000))
USERS       = set(os.environ.get("USERS", "hal,propinas,tips").split(","))

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def clnrest(method, params=None):
    url  = f"{CLNREST_URL}/v1/{method}"
    data = json.dumps(params or {}).encode()
    req  = urllib.request.Request(url, data=data,
           headers={"Rune": RUNE, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return json.loads(r.read())

class LNURLHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # Step 1 — metadata
        if path.startswith("/.well-known/lnurlp/"):
            username = path.split("/")[-1]
            if username not in USERS:
                self.send_json(404, {"status": "ERROR", "reason": "user not found"})
                return
            self.send_json(200, {
                "tag":            "payRequest",
                "callback":       f"https://{DOMAIN}/lnurlp/callback/{username}",
                "minSendable":    MIN_SATS * 1000,
                "maxSendable":    MAX_SATS * 1000,
                "metadata":       json.dumps([["text/plain", f"{username}@{DOMAIN}"]]),
                "commentAllowed": 255,
            })

        # Step 2 — invoice
        elif path.startswith("/lnurlp/callback/"):
            username    = path.split("/")[-1]
            amount_msat = int(params.get("amount", [0])[0])
            comment     = params.get("comment", [""])[0][:255]
            description = f"{username}@{DOMAIN}" + (f": {comment}" if comment else "")

            if username not in USERS:
                self.send_json(404, {"status": "ERROR", "reason": "user not found"})
                return
            if not (MIN_SATS * 1000 <= amount_msat <= MAX_SATS * 1000):
                self.send_json(400, {"status": "ERROR", "reason": "amount out of range"})
                return
            try:
                resp = clnrest("invoice", {
                    "amount_msat": amount_msat,
                    "label":       f"lnaddr-{username}-{time.time_ns()}",
                    "description": description,
                })
                self.send_json(200, {"pr": resp["bolt11"], "routes": []})
            except Exception as e:
                self.send_json(500, {"status": "ERROR", "reason": str(e)})

        else:
            self.send_json(404, {"status": "ERROR", "reason": "not found"})

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), LNURLHandler)
    print(f"LNURL server listening on {DOMAIN} port {PORT}")
    server.serve_forever()
