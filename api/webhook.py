import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

from dotenv import load_dotenv

from crm_sync import log_event, process_webhook_payload

load_dotenv()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        mode = params.get("hub.mode", [None])[0]
        token = params.get("hub.verify_token", [None])[0]
        challenge = params.get("hub.challenge", [None])[0]

        if mode == "subscribe" and token == os.getenv("FB_VERIFY_TOKEN"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write((challenge or "").encode())
            log_event("Webhook verified successfully")
            return

        self.send_response(403)
        self.end_headers()
        self.wfile.write(b"Forbidden")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body or b"{}")
            log_event("Webhook POST received", payload=data)
            processed = process_webhook_payload(data)
            if not processed:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"message": "Not a lead event", "processed": 0}')
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"success": True, "processed": len(processed), "leads": processed}
            self.wfile.write(json.dumps(response).encode())
        except Exception as exc:
            log_event("Webhook processing failed", error=str(exc))
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())
