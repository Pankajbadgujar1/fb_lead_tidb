"""
Google Ads Lead Form Webhook
Add this route to your existing api/index.py
"""

import json
import logging
import os
import pymysql
from flask import jsonify, request


def get_db_connection():
    """Reuses same TiDB connection pattern as your existing code."""
    return pymysql.connect(
        host=os.environ.get("TIDB_HOST"),
        port=int(os.environ.get("TIDB_PORT", 4000)),
        user=os.environ.get("TIDB_USER"),
        password=os.environ.get("TIDB_PASSWORD"),
        database=os.environ.get("TIDB_DB") or os.environ.get("TIDB_DATABASE"),
        ssl={"verify_cert": True, "verify_identity": True},
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
    )


def ensure_google_leads_table():
    """Creates google_ads_leads table if it doesn't exist."""
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS google_ads_leads (
                    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
                    full_name   VARCHAR(255),
                    phone       VARCHAR(50),
                    email       VARCHAR(255),
                    city        VARCHAR(100),
                    campaign    VARCHAR(255),
                    ad_id       VARCHAR(100),
                    form_id     VARCHAR(100),
                    raw_data    JSON,
                    source      VARCHAR(50) DEFAULT 'google_ads',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
    logging.info("google_ads_leads table ready")


def register_google_ads_routes(app):
    """
    Call this function in your api/index.py to register the Google Ads routes.

    Usage in api/index.py:
        from google_ads_webhook import register_google_ads_routes
        register_google_ads_routes(app)
    """

    @app.route("/api/google-leads", methods=["GET"])
    def google_ads_verify():
        """
        Google Ads sends a GET request to verify the webhook.
        It expects a 200 OK with the challenge echoed back.
        """
        challenge = request.args.get("challenge")
        token = request.args.get("token") or request.args.get("key")
        expected_token = os.environ.get("GOOGLE_WEBHOOK_TOKEN", "")

        logging.info("Google Ads webhook verification request received")

        # If you set GOOGLE_WEBHOOK_TOKEN in .env, validate it
        if expected_token and token != expected_token:
            logging.warning("Google Ads webhook token mismatch")
            return "Forbidden", 403

        # Echo the challenge back — Google Ads requires this
        return challenge or "OK", 200

    @app.route("/api/google-leads", methods=["POST"])
    def google_ads_webhook():
        """
        Receives lead data from Google Ads Lead Form.
        Google sends JSON like:
        {
            "lead_id": "...",
            "user_column_data": [
                {"column_name": "FULL_NAME", "string_value": "John Doe"},
                {"column_name": "PHONE_NUMBER", "string_value": "+91..."},
                {"column_name": "EMAIL", "string_value": "john@example.com"},
                {"column_name": "CITY", "string_value": "Pune"}
            ],
            "campaign_id": "...",
            "ad_id": "...",
            "form_id": "..."
        }
        """
        data = request.get_json(silent=True) or {}
        logging.info("Google Ads lead received: lead_id=%s is_test=%s", data.get("lead_id"), data.get("is_test"))

        expected_token = os.environ.get("GOOGLE_WEBHOOK_TOKEN", "")
        received_token = (
            data.get("google_key")
            or request.args.get("key")
            or request.args.get("token")
        )

        if expected_token and received_token != expected_token:
            logging.warning("Google Ads webhook key mismatch")
            return jsonify({"message": "Invalid google_key"}), 400

        # Parse Google Ads lead fields
        user_columns = data.get("user_column_data", [])
        fields = {}
        for col in user_columns:
            key = (col.get("column_id") or col.get("column_name") or "").upper()
            value = col.get("string_value") or col.get("string_values", [None])[0] or ""
            fields[key] = value

        full_name   = fields.get("FULL_NAME", "") or fields.get("NAME", "")
        phone       = fields.get("PHONE_NUMBER", "") or fields.get("PHONE", "")
        email       = fields.get("EMAIL", "")
        city        = fields.get("CITY", "") or fields.get("LOCATION", "") or fields.get("REGION", "")
        campaign    = str(data.get("campaign_id", ""))
        ad_id       = str(data.get("ad_id") or data.get("creative_id") or "")
        form_id     = str(data.get("form_id", ""))

        logging.info(
            "Parsed lead — name=%s phone=%s email=%s city=%s",
            full_name, phone, email, city
        )

        # Save to TiDB
        try:
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO google_ads_leads
                            (full_name, phone, email, city, campaign, ad_id, form_id, raw_data)
                        VALUES
                            (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            full_name or None,
                            phone or None,
                            email or None,
                            city or None,
                            campaign or None,
                            ad_id or None,
                            form_id or None,
                            json.dumps(data),    # store valid JSON
                        ),
                    )
                conn.commit()

            logging.info("Google Ads lead saved to TiDB")
            return jsonify({}), 200

        except Exception as exc:
            logging.error("Failed to save Google Ads lead: %s", exc)
            # Always return 200 to Google so it doesn't retry endlessly
            return jsonify({}), 200
