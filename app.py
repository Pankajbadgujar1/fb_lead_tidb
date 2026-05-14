
import os
from flask import Flask, request
from crm_sync import (
    log_event,
    process_webhook_payload,
    save_contact_and_opportunity_to_tidb,
    save_opportunity_to_tidb,
)
# Existing blueprint
from routes.crm_ingest import crm_ingest_bp

# NEW: X (Twitter) Lead Ads webhook
from routes.twitter_webhook import twitter_bp
from webhooks.linkedin import linkedin_bp

app = Flask(__name__)

app.register_blueprint(crm_ingest_bp)
app.register_blueprint(twitter_bp)          # → /api/twitter/webhook
app.register_blueprint(linkedin_bp)         # -> /webhook/linkedin


@app.route("/api/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == os.getenv("FB_VERIFY_TOKEN"):
            return challenge
        return "Forbidden", 403

    data = request.get_json(silent=True) or {}
    log_event("Webhook POST received", payload=data)
    try:
        processed = process_webhook_payload(data)
        if not processed:
            return {"message": "Not a lead event", "processed": 0}
        return {"success": True, "processed": len(processed), "leads": processed}
    except Exception as exc:
        log_event("Webhook processing failed", error=str(exc), payload=data)
        return {"error": str(exc)}, 500


if __name__ == "__main__":
    app.run()
