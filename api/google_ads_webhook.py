"""
Google Ads Lead Form Webhook.

The webhook writes Google Ads lead submissions directly into crm_Opportunities.
"""

import json
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation

import pymysql
from flask import jsonify, request


def get_db_connection():
    """Reuses the same TiDB connection pattern as the rest of the app."""
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


def _first_non_empty(*values):
    for value in values:
        value = _truncate(value, 191)
        if value:
            return value
    return None


def _column_value(column):
    value = column.get("string_value")
    if value not in (None, ""):
        return str(value).strip()

    values = column.get("string_values") or column.get("values") or []
    if values:
        return str(values[0]).strip()

    return ""


def _parse_google_fields(user_columns):
    fields = {}
    for column in user_columns or []:
        key = (column.get("column_id") or column.get("column_name") or "").strip()
        if not key:
            continue
        fields[key.upper()] = _column_value(column)
    return fields


def build_google_opportunity_record(data):
    fields = _parse_google_fields(data.get("user_column_data", []))

    full_name = _first_non_empty(fields.get("FULL_NAME"), fields.get("NAME"))
    phone = _first_non_empty(fields.get("PHONE_NUMBER"), fields.get("PHONE"))
    email = _first_non_empty(fields.get("EMAIL"))
    city = _first_non_empty(fields.get("CITY"), fields.get("LOCATION"), fields.get("REGION"))

    lead_id = _first_non_empty(data.get("lead_id"), data.get("google_lead_id"))
    ad_id = _first_non_empty(data.get("ad_id"), data.get("creative_id"))
    form_id = _first_non_empty(data.get("form_id"), data.get("lead_form_id"))
    google_campaign_id = _first_non_empty(data.get("campaign_id"))

    label = _first_non_empty(full_name, email, phone, lead_id, "Google Ads Lead")
    description_parts = [
        f"lead_id={lead_id}" if lead_id else None,
        f"campaign_id={google_campaign_id}" if google_campaign_id else None,
        f"ad_id={ad_id}" if ad_id else None,
        f"form_id={form_id}" if form_id else None,
    ]

    custom_fields_data = {
        "google_ads": {
            "lead_id": lead_id,
            "campaign_id": google_campaign_id,
            "ad_id": ad_id,
            "form_id": form_id,
            "is_test": data.get("is_test"),
            "fields": fields,
        }
    }

    opportunity_id = (
        f"google-opportunity-{lead_id}"
        if lead_id
        else f"google-opportunity-{uuid.uuid4()}"
    )
    default_user_id = os.environ.get("CRM_DEFAULT_USER_ID")

    return {
        "id": _truncate(opportunity_id, 191),
        "account": _truncate(os.environ.get("CRM_DEFAULT_ACCOUNT_ID"), 191),
        "assigned_to": _truncate(default_user_id, 191),
        "budget": _parse_decimal(data.get("budget")),
        "campaign": _truncate(os.environ.get("CRM_DEFAULT_CAMPAIGN_ID"), 191),
        "close_date": None,
        "contact": None,
        "created_by": _truncate(default_user_id, 191),
        "createdBy": _truncate(default_user_id, 191),
        "updatedBy": _truncate(default_user_id, 191),
        "currency": _truncate(data.get("currency"), 3),
        "snapshot_rate": None,
        "description": _truncate("; ".join(part for part in description_parts if part), 191),
        "expected_revenue": _parse_decimal(data.get("expected_revenue") or data.get("budget")),
        "name": _truncate(f"Google Ads Lead - {label}", 191),
        "next_step": _truncate(f"Follow up with {email or phone or 'lead'}", 191),
        "sales_stage": _truncate(os.environ.get("CRM_DEFAULT_SALES_STAGE_ID"), 191),
        "type": _truncate(os.environ.get("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"), 191),
        "status": "ACTIVE",
        "category": _truncate("google_ads", 191),
        "clientName": _truncate(full_name, 191),
        "custom_fields_data": json.dumps(custom_fields_data),
        "phone": _truncate(phone, 50),
        "email": _truncate(email, 255),
        "city": _truncate(city, 100),
        "ad_id": _truncate(ad_id, 100),
        "form_id": _truncate(form_id, 100),
        "source": _truncate("google_ads", 50),
        "raw_data": json.dumps(data),
    }


def save_google_opportunity(record):
    sql = """
        INSERT INTO crm_Opportunities (
            id, account, assigned_to, budget, campaign, close_date, contact,
            created_by, createdBy, updatedBy, currency, snapshot_rate, description,
            expected_revenue, name, next_step, sales_stage, type, status, category,
            clientName, custom_fields_data, phone, email, city, ad_id, form_id,
            source, raw_data
        ) VALUES (
            %(id)s, %(account)s, %(assigned_to)s, %(budget)s, %(campaign)s, %(close_date)s,
            %(contact)s, %(created_by)s, %(createdBy)s, %(updatedBy)s, %(currency)s,
            %(snapshot_rate)s, %(description)s, %(expected_revenue)s, %(name)s,
            %(next_step)s, %(sales_stage)s, %(type)s, %(status)s, %(category)s,
            %(clientName)s, %(custom_fields_data)s, %(phone)s, %(email)s, %(city)s,
            %(ad_id)s, %(form_id)s, %(source)s, %(raw_data)s
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
            category = VALUES(category),
            clientName = VALUES(clientName),
            custom_fields_data = VALUES(custom_fields_data),
            phone = VALUES(phone),
            email = VALUES(email),
            city = VALUES(city),
            ad_id = VALUES(ad_id),
            form_id = VALUES(form_id),
            source = VALUES(source),
            raw_data = VALUES(raw_data),
            updatedAt = CURRENT_TIMESTAMP(3)
    """

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, record)
        conn.commit()


def register_google_ads_routes(app):
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

        if expected_token and token != expected_token:
            logging.warning("Google Ads webhook token mismatch")
            return "Forbidden", 403

        return challenge or "OK", 200

    @app.route("/api/google-leads", methods=["POST"])
    def google_ads_webhook():
        """
        Receives Google Ads lead data and stores it in crm_Opportunities.
        """
        data = request.get_json(silent=True) or {}
        logging.info(
            "Google Ads lead received: lead_id=%s is_test=%s",
            data.get("lead_id"),
            data.get("is_test"),
        )

        expected_token = os.environ.get("GOOGLE_WEBHOOK_TOKEN", "")
        received_token = (
            data.get("google_key")
            or request.args.get("key")
            or request.args.get("token")
        )

        if expected_token and received_token != expected_token:
            logging.warning("Google Ads webhook key mismatch")
            return jsonify({"message": "Invalid google_key"}), 400

        record = build_google_opportunity_record(data)
        logging.info(
            "Parsed Google Ads lead for opportunity: id=%s name=%s phone=%s email=%s city=%s",
            record["id"],
            record["clientName"],
            record["phone"],
            record["email"],
            record["city"],
        )

        try:
            save_google_opportunity(record)
            logging.info("Google Ads lead saved to crm_Opportunities: %s", record["id"])
            return jsonify({}), 200
        except Exception as exc:
            logging.error("Failed to save Google Ads lead: %s", exc)
            return jsonify({}), 200
