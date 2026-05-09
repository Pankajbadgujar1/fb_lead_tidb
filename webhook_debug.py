import json
import os

from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


@app.route("/api/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        payload = {
            "mode": request.args.get("hub.mode"),
            "verify_token": request.args.get("hub.verify_token"),
            "challenge": request.args.get("hub.challenge"),
            "expected_token": os.getenv("FB_VERIFY_TOKEN"),
        }
        print("Verification request received:")
        print(json.dumps(payload, indent=2))

        if (
            payload["mode"] == "subscribe"
            and payload["verify_token"] == payload["expected_token"]
        ):
            return payload["challenge"] or "", 200
        return "Forbidden", 403

    payload = request.get_json(silent=True)
    debug_record = {
        "headers": dict(request.headers),
        "args": request.args.to_dict(flat=False),
        "json": payload,
        "raw_body": request.get_data(as_text=True),
    }
    print("Webhook POST received:")
    print(json.dumps(debug_record, indent=2))
    return jsonify({"received": True}), 200


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOK_DEBUG_PORT", "3000"))
    app.run(host="0.0.0.0", port=port, debug=True)
