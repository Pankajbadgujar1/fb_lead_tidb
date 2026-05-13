import hashlib
import hmac
import json
import logging
import os
from decimal import Decimal, InvalidOperation
import uuid

import pymysql
import requests
from dotenv import load_dotenv
from flask import Flask, request

from routes.crm_ingest import crm_ingest_bp
from routes.twitter_webhook import twitter_bp


load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Register CRM ingest blueprint (POST /api/crm/contacts/ingest)
app.register_blueprint(crm_ingest_bp)
app.register_blueprint(twitter_bp)

GRAPH_API_VERSION = "v19.0"
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN") or os.environ.get("FB_VERIFY_TOKEN")
APP_SECRET = os.environ.get("APP_SECRET") or os.environ.get("APP_SCREAT")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN") or os.environ.get(
    "FB_PAGE_ACCESS_TOKEN"
)

CRM_DEFAULT_USER_ID = os.environ.get("CRM_DEFAULT_USER_ID")
CRM_DEFAULT_ACCOUNT_ID = os.environ.get("CRM_DEFAULT_ACCOUNT_ID")
CRM_DEFAULT_CAMPAIGN_ID = os.environ.get("CRM_DEFAULT_CAMPAIGN_ID")
CRM_DEFAULT_SALES_STAGE_ID = os.environ.get("CRM_DEFAULT_SALES_STAGE_ID")
CRM_DEFAULT_OPPORTUNITY_TYPE_ID = os.environ.get("CRM_DEFAULT_OPPORTUNITY_TYPE_ID")
CRM_DEFAULT_OPPORTUNITY_STATUS = os.environ.get("CRM_DEFAULT_OPPORTUNITY_STATUS")

WEBHOOK_LOG_MAX_CHARS = int(os.environ.get("WEBHOOK_LOG_MAX_CHARS", "4000"))


def _log_json(label, payload, max_chars=WEBHOOK_LOG_MAX_CHARS):
    try:
        text = json.dumps(payload, default=str, ensure_ascii=True)
    except Exception:
        text = str(payload)
    if len(text) > max_chars:
        text = text[:max_chars] + "...(truncated)"
    logging.info("%s: %s", label, text)


def get_db_connection():
    return pymysql.connect(
        host=os.environ.get("TIDB_HOST"),
        port=int(os.environ.get("TIDB_PORT", 4000)),
        user=os.environ.get("TIDB_USER"),
        password=os.environ.get("TIDB_PASSWORD"),
        database=os.environ.get("TIDB_DB") or os.environ.get("TIDB_DATABASE"),
        ssl={"verify_cert": True, "verify_identity": True},
        connect_timeout=10,
        read_timeout=10,
        write_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
    )


def verify_signature(payload_body, signature_header):
    if not APP_SECRET:
        logging.error("APP_SECRET is not configured")
        return False

    if not signature_header:
        logging.warning("Missing X-Hub-Signature-256 header")
        return False

    expected_signature = "sha256=" + hmac.new(
        APP_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)


def fetch_lead_data(leadgen_id):
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{leadgen_id}"
    params = {
        "fields": "field_data",
        "access_token": PAGE_ACCESS_TOKEN,
    }

    try:
        logging.info("Fetching lead data from Graph API: %s", leadgen_id)
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logging.error("Graph API request failed for %s: %s", leadgen_id, exc)
    except ValueError as exc:
        logging.error("Graph API returned invalid JSON for %s: %s", leadgen_id, exc)

    return None


def parse_field_data(field_data):
    result = {
        "full_name": "",
        "email": "",
        "phone": "",
    }

    for field in field_data or []:
        field_name = field.get("name", "").lower()
        values = field.get("values", [])
        value = values[0] if values else ""

        if "name" in field_name:
            result["full_name"] = value
        elif "email" in field_name:
            result["email"] = value
        elif "phone" in field_name:
            result["phone"] = value

    return result


def _truncate(value, max_length):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:max_length]


def _parse_decimal(raw_value):
    if raw_value is None:
        return Decimal("0")
    cleaned = str(raw_value).replace(",", "").replace("$", "").strip()
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _normalize_fields(field_data):
    fields = {}
    for field in field_data or []:
        name = (field.get("name") or "").strip().lower()
        values = field.get("values") or []
        if not name or not values:
            continue
        fields[name] = str(values[0]).strip()
    return fields


def _first_non_empty(*values):
    for value in values:
        value = _truncate(value, 191)
        if value:
            return value
    return None


def build_opportunity_record(leadgen_id, page_id, lead_data, lead_info):
    fields = _normalize_fields(lead_data.get("field_data", []))
    company = _first_non_empty(fields.get("company_name"), fields.get("company"))
    message = _first_non_empty(fields.get("message"), fields.get("comments"), fields.get("note"))

    full_name = _first_non_empty(lead_info.get("full_name"), fields.get("full_name"), fields.get("name"))
    email = _first_non_empty(lead_info.get("email"), fields.get("email"))
    phone = _first_non_empty(
        lead_info.get("phone"),
        fields.get("phone_number"),
        fields.get("phone"),
        fields.get("mobile_phone"),
    )

    lead_label = _first_non_empty(company, full_name, email, phone, f"Facebook Lead {leadgen_id}")
    name = _truncate(f"Facebook Lead - {lead_label}", 191) or _truncate(lead_label, 191)

    # Keep these <= 191 to match crm_Opportunities column sizes.
    description_parts = [
        f"leadgen_id={leadgen_id}",
        f"page_id={page_id}" if page_id else None,
        f"email={email}" if email else None,
        f"phone={phone}" if phone else None,
        message,
    ]
    description = _truncate("; ".join([p for p in description_parts if p]), 191)
    next_step = _truncate(f"Follow up with {email or phone or 'lead'}", 191)

    budget = _parse_decimal(fields.get("budget"))
    expected_revenue = budget

    status = (CRM_DEFAULT_OPPORTUNITY_STATUS or "ACTIVE").strip().upper() or "ACTIVE"

    return {
        "id": _truncate(f"fb-opportunity-{leadgen_id}", 191),
        "account": _truncate(CRM_DEFAULT_ACCOUNT_ID, 191),
        "assigned_to": _truncate(CRM_DEFAULT_USER_ID, 191),
        "budget": budget,
        "campaign": _truncate(CRM_DEFAULT_CAMPAIGN_ID, 191),
        "close_date": None,
        "contact": _truncate(f"fb-contact-{leadgen_id}", 191),
        "created_by": _truncate(CRM_DEFAULT_USER_ID, 191),
        "createdBy": _truncate(CRM_DEFAULT_USER_ID, 191),
        "updatedBy": _truncate(CRM_DEFAULT_USER_ID, 191),
        "currency": None,
        "snapshot_rate": None,
        "description": description,
        "expected_revenue": expected_revenue,
        "name": name,
        "next_step": next_step,
        "sales_stage": _truncate(CRM_DEFAULT_SALES_STAGE_ID, 191),
        "type": _truncate(CRM_DEFAULT_OPPORTUNITY_TYPE_ID, 191),
        "status": status,
        "clientName": _first_non_empty(company, full_name),
    }


def save_opportunity_to_db(record):
    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO crm_Opportunities (
                        id, account, assigned_to, budget, campaign, close_date, contact,
                        created_by, createdBy, updatedBy, currency, snapshot_rate, description,
                        expected_revenue, name, next_step, sales_stage, type, status, clientName
                    ) VALUES (
                        %(id)s, %(account)s, %(assigned_to)s, %(budget)s, %(campaign)s, %(close_date)s, %(contact)s,
                        %(created_by)s, %(createdBy)s, %(updatedBy)s, %(currency)s, %(snapshot_rate)s, %(description)s,
                        %(expected_revenue)s, %(name)s, %(next_step)s, %(sales_stage)s, %(type)s, %(status)s, %(clientName)s
                    )
                    ON DUPLICATE KEY UPDATE
                        account = VALUES(account),
                        assigned_to = VALUES(assigned_to),
                        budget = VALUES(budget),
                        campaign = VALUES(campaign),
                        close_date = VALUES(close_date),
                        contact = VALUES(contact),
                        created_by = VALUES(created_by),
                        createdBy = VALUES(createdBy),
                        updatedBy = VALUES(updatedBy),
                        currency = VALUES(currency),
                        snapshot_rate = VALUES(snapshot_rate),
                        description = VALUES(description),
                        expected_revenue = VALUES(expected_revenue),
                        name = VALUES(name),
                        next_step = VALUES(next_step),
                        sales_stage = VALUES(sales_stage),
                        type = VALUES(type),
                        status = VALUES(status),
                        clientName = VALUES(clientName),
                        updatedAt = CURRENT_TIMESTAMP(3)
                    """
                )
            conn.commit()
        logging.info("Opportunity saved or updated: %s", record.get("id"))
    except Exception as exc:
        logging.error("DB error for opportunity %s: %s", record.get("id"), exc)


def extract_lead_event(data):
    entry = data.get("entry", [])[0]
    change = entry.get("changes", [])[0]
    value = change.get("value", {})

    return value.get("leadgen_id"), value.get("page_id")


@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200


@app.route("/webhook", methods=["GET"])
@app.route("/api/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    logging.info("Webhook verification requested")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("Webhook verified successfully")
        return challenge or "", 200, {"Content-Type": "text/plain"}

    logging.warning("Webhook verification failed")
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
@app.route("/api/webhook", methods=["POST"])
def receive_webhook():
    logging.info("Step 1: Receive POST /webhook")
    raw_body = request.get_data() or b""
    signature = request.headers.get("X-Hub-Signature-256")

    if raw_body:
        try:
            body_preview = raw_body[:WEBHOOK_LOG_MAX_CHARS].decode(
                "utf-8", errors="replace"
            )
        except Exception:
            body_preview = str(raw_body[:WEBHOOK_LOG_MAX_CHARS])
        if len(raw_body) > WEBHOOK_LOG_MAX_CHARS:
            body_preview += "...(truncated)"
        logging.info("Webhook raw body: %s", body_preview)

    # Allow missing signature for manual testing; verify if header is present.
    if signature and not verify_signature(raw_body, signature):
        logging.warning("Signature verification failed; returning 200 OK per requirement")
        return "OK", 200

    data = request.get_json(silent=True) or {}
    _log_json("Webhook payload", data)

    logging.info("Step 2: Extract leadgen_id and page_id")
    leadgen_id, page_id = None, None
    try:
        leadgen_id, page_id = extract_lead_event(data)
    except Exception as exc:
        logging.error("Failed extracting lead event: %s", exc)

    logging.info("leadgen_id=%s page_id=%s", leadgen_id, page_id)
    if not leadgen_id:
        logging.warning("leadgen_id missing; nothing to insert")
        return "OK", 200

    logging.info("Step 3: Generate UUID for crm_Opportunities.id")
    opportunity_id = str(uuid.uuid4())
    logging.info("generated id=%s", opportunity_id)

    logging.info("Step 4: Fetch lead details from Graph API (best-effort)")
    lead_full_name = "Facebook Lead"
    lead_email = ""
    lead_phone = ""
    lead_data = None
    try:
        lead_data = fetch_lead_data(leadgen_id)
        if lead_data is not None:
            _log_json("Graph API lead data", lead_data)
    except Exception as exc:
        logging.error("Graph API fetch threw exception: %s", exc)

    logging.info("Step 5: ALWAYS save to DB (Graph API success/failure)")
    if lead_data:
        logging.info("Step 6: Graph API succeeded; extracting name/email/phone")
        lead_info = parse_field_data(lead_data.get("field_data", []))
        lead_full_name = (lead_info.get("full_name") or "Facebook Lead").strip() or "Facebook Lead"
        lead_email = (lead_info.get("email") or "").strip()
        lead_phone = (lead_info.get("phone") or "").strip()
    else:
        logging.info("Step 7: Graph API failed/empty; using fallback values")

    # Enforce column size limits.
    name_value = _truncate(str(leadgen_id), 191) or ""
    client_name_value = _truncate(lead_full_name, 191) or "Facebook Lead"
    description_value = _truncate(lead_email, 191) or ""
    next_step_value = _truncate(lead_phone, 191) or ""

    logging.info("Step 8: INSERT into crm_Opportunities")
    logging.info(
        "Insert values id=%s name=%s clientName=%s description=%s next_step=%s",
        opportunity_id,
        name_value,
        client_name_value,
        description_value,
        next_step_value,
    )

    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO crm_Opportunities
                    (id, name, clientName, description, next_step,
                     status, budget, expected_revenue, createdAt, updatedAt)
                    VALUES
                    (%s, %s, %s, %s, %s, 'ACTIVE', 0, 0, NOW(), NOW())
                    """,
                    (
                        opportunity_id,
                        name_value,
                        client_name_value,
                        description_value,
                        next_step_value,
                    ),
                )
            conn.commit()
        logging.info("Insert successful for id=%s", opportunity_id)
    except Exception as exc:
        logging.error("Insert failed for id=%s error=%s", opportunity_id, exc)

    logging.info("Step 9: Return 200 OK always")
    return "OK", 200


if __name__ == "__main__":
    app.run(debug=True)


# ─── Google Ads Lead Form Webhook ───────────────────────────────────────────
try:
    from .google_ads_webhook import register_google_ads_routes
except ImportError:
    from google_ads_webhook import register_google_ads_routes

# Register /api/google-leads GET + POST routes
register_google_ads_routes(app)
