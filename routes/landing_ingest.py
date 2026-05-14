"""Generic landing-page CRM ingest API.

Endpoint:
  POST /api/crm/leads/submit

This is the shareable API for any landing page. It accepts normalized lead
fields and writes one complete CRM lead pipeline:
  crm_Contacts -> crm_Opportunities -> ContactsToOpportunities -> crm_Leads
"""

import json
import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, make_response, request

from crm_sync import get_connection, log_event


landing_ingest_bp = Blueprint("landing_ingest", __name__, url_prefix="/api/crm")


def _json_response(payload, status=200):
    response = make_response(payload, status)
    response.headers["Access-Control-Allow-Origin"] = os.getenv(
        "CRM_INGEST_ALLOWED_ORIGIN",
        "*",
    )
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    return response


def _require_api_key():
    expected = os.getenv("CRM_INGEST_API_KEY")
    if not expected:
        return None

    provided = request.headers.get("X-API-Key") or request.args.get("api_key")
    if provided != expected:
        return _json_response({"success": False, "error": "Invalid API key."}, 401)
    return None


def _clean(value, max_length=191):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:max_length]


def _pick(payload, *names):
    for name in names:
        value = _clean(payload.get(name), 500)
        if value:
            return value
    return None


def _split_name(full_name, email=None, phone=None):
    full_name = _clean(full_name, 191)
    if full_name:
        parts = full_name.split()
        if len(parts) == 1:
            return parts[0], "Lead"
        return _clean(parts[0], 191), _clean(" ".join(parts[1:]), 191)

    fallback = email or phone or "Landing Lead"
    return _clean(fallback, 191), "Lead"


def _parse_decimal(value):
    value = _clean(value, 50)
    if not value:
        return Decimal("0")
    cleaned = value.replace(",", "").replace("$", "").replace("₹", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _status_value(value):
    status = (_clean(value, 191) or "ACTIVE").upper()
    allowed = {"ACTIVE", "INACTIVE", "PENDING", "CLOSED"}
    if status not in allowed:
        return "ACTIVE"
    return status


def _source(payload):
    return (_clean(payload.get("source_platform") or payload.get("source"), 50) or "landing_page").lower()


def _external_id(payload):
    return _clean(
        payload.get("external_lead_id")
        or payload.get("lead_id")
        or payload.get("id"),
        100,
    )


def _validate(payload):
    full_name = _pick(payload, "full_name", "name")
    email = _pick(payload, "email", "personal_email")
    phone = _pick(payload, "phone", "phone_number", "mobile_phone")

    if not full_name:
        return "full_name or name is required."
    if not email and not phone:
        return "email or phone is required."
    if email and "@" not in email:
        return "email must contain '@'."
    return None


def _meta(payload):
    source = _source(payload)
    external_id = _external_id(payload) or str(uuid.uuid4())
    campaign = _clean(
        payload.get("campaign_id")
        or payload.get("campaign")
        or payload.get("utm_campaign"),
        191,
    )
    return {
        "source": source,
        "external_id": external_id,
        "campaign": campaign,
        "utm_source": _clean(payload.get("utm_source"), 100),
        "utm_medium": _clean(payload.get("utm_medium"), 100),
        "utm_campaign": _clean(payload.get("utm_campaign"), 191),
        "utm_term": _clean(payload.get("utm_term"), 191),
        "utm_content": _clean(payload.get("utm_content"), 191),
        "click_id": _clean(
            payload.get("click_id")
            or payload.get("twclid")
            or payload.get("gclid")
            or payload.get("fbclid"),
            191,
        ),
        "raw": payload,
    }


def _lead_description(payload, meta):
    message = _pick(payload, "message", "comments", "description", "about")
    parts = [
        f"Source: {meta['source']}",
        f"External lead: {meta['external_id']}",
        f"Campaign: {meta['campaign']}" if meta.get("campaign") else None,
        message,
    ]
    return _clean(" | ".join(part for part in parts if part), 191)


def _save_contact(cursor, payload, meta):
    email = _clean(_pick(payload, "email", "personal_email"), 191)
    phone = _clean(_pick(payload, "phone", "phone_number", "mobile_phone"), 191)
    full_name = _pick(payload, "full_name", "name")
    first_name, last_name = _split_name(full_name, email, phone)

    source = meta["source"]
    contact_id = _clean(f"{source}-contact-{meta['external_id']}", 191)
    default_account_id = _clean(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191)
    default_user_id = _clean(os.getenv("CRM_DEFAULT_USER_ID"), 191)
    contact_type_id = _clean(os.getenv("CRM_DEFAULT_CONTACT_TYPE_ID"), 191)

    notes = json.dumps(
        [
            {
                "source": "generic_landing_page_api",
                **meta,
            }
        ],
        default=str,
    )

    sql = """
        INSERT INTO crm_Contacts (
            id, account, assigned_to, created_by, createdBy, updatedBy,
            description, email, personal_email, first_name, last_name,
            office_phone, mobile_phone, website, position, contact_type_id,
            tags, notes, accountsIDs, address, address_line1, address_line2,
            city, country, postal_code, state
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            description = VALUES(description),
            email = VALUES(email),
            mobile_phone = VALUES(mobile_phone),
            website = VALUES(website),
            position = VALUES(position),
            notes = VALUES(notes),
            city = VALUES(city),
            country = VALUES(country),
            state = VALUES(state),
            updatedBy = VALUES(updatedBy)
    """
    values = (
        contact_id,
        default_account_id,
        default_user_id,
        default_user_id,
        default_user_id,
        default_user_id,
        _lead_description(payload, meta),
        email,
        _clean(payload.get("personal_email"), 191),
        first_name,
        last_name or "Lead",
        _clean(payload.get("office_phone"), 191),
        phone,
        _clean(payload.get("website"), 191),
        _clean(_pick(payload, "job_title", "position", "headline"), 191),
        contact_type_id,
        json.dumps([source, "landing_page"]),
        notes,
        default_account_id,
        _clean(payload.get("address"), 191),
        _clean(payload.get("address_line1"), 191),
        _clean(payload.get("address_line2"), 191),
        _clean(payload.get("city"), 191),
        _clean(payload.get("country"), 191),
        _clean(_pick(payload, "postal_code", "zip"), 191),
        _clean(payload.get("state"), 191),
    )
    cursor.execute(sql, values)
    return contact_id


def _save_opportunity(cursor, payload, meta, contact_id):
    source = meta["source"]
    opportunity_id = _clean(f"{source}-opportunity-{meta['external_id']}", 191)
    full_name = _pick(payload, "full_name", "name")
    company = _pick(payload, "company", "company_name", "business_name")
    opportunity_name = _clean(
        payload.get("opportunity_name")
        or payload.get("plan_type")
        or company
        or full_name
        or f"{source} lead",
        191,
    )

    default_account_id = _clean(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191)
    default_user_id = _clean(os.getenv("CRM_DEFAULT_USER_ID"), 191)
    default_campaign_id = _clean(
        payload.get("crm_campaign_id") or os.getenv("CRM_DEFAULT_CAMPAIGN_ID"),
        191,
    )
    default_sales_stage = _clean(os.getenv("CRM_DEFAULT_SALES_STAGE_ID"), 191)
    default_opp_type = _clean(os.getenv("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"), 191)

    raw_data = json.dumps({"meta": meta, "payload": payload}, default=str)
    email = _clean(_pick(payload, "email", "personal_email"), 255)
    phone = _clean(_pick(payload, "phone", "phone_number", "mobile_phone"), 50)

    sql = """
        INSERT INTO crm_Opportunities (
            id, name, account, assigned_to, created_by, createdBy, updatedBy,
            contact, campaign, sales_stage, type, status, description,
            budget, expected_revenue, currency, snapshot_rate, close_date,
            next_step, source, ad_id, form_id, email, phone, city,
            raw_data, clientName, category, custom_fields_data
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            description = VALUES(description),
            source = VALUES(source),
            ad_id = VALUES(ad_id),
            form_id = VALUES(form_id),
            email = VALUES(email),
            phone = VALUES(phone),
            city = VALUES(city),
            raw_data = VALUES(raw_data),
            clientName = VALUES(clientName),
            updatedBy = VALUES(updatedBy)
    """
    values = (
        opportunity_id,
        opportunity_name,
        default_account_id,
        default_user_id,
        default_user_id,
        default_user_id,
        default_user_id,
        contact_id,
        default_campaign_id,
        default_sales_stage,
        default_opp_type,
        _status_value(payload.get("status")),
        _lead_description(payload, meta),
        _parse_decimal(payload.get("budget")),
        _parse_decimal(payload.get("expected_revenue") or payload.get("budget")),
        _clean(payload.get("currency"), 3),
        None,
        None,
        _clean(payload.get("next_step"), 191),
        source,
        _clean(_pick(payload, "ad_id", "creative_id", "card_id"), 100),
        _clean(meta.get("campaign"), 100),
        email,
        phone,
        _clean(payload.get("city"), 100),
        raw_data,
        _clean(full_name or company, 191),
        _clean(payload.get("category"), 191),
        json.dumps(payload.get("custom_fields") or {}, default=str),
    )
    cursor.execute(sql, values)
    return opportunity_id


def _save_lead(cursor, payload, meta):
    email = _clean(_pick(payload, "email", "personal_email"), 191)
    phone = _clean(_pick(payload, "phone", "phone_number", "mobile_phone"), 191)
    full_name = _pick(payload, "full_name", "name")
    first_name, last_name = _split_name(full_name, email, phone)
    lead_id = str(uuid.uuid4())
    source = meta["source"]

    sql = """
        INSERT INTO crm_Leads (
            id, firstName, lastName, email, phone, mobile_phone, personal_email,
            office_phone, company, jobTitle, position, description,
            source_platform, twitter, headline, website, linkedin_url,
            username, message_snippet, message_date, city, country, state,
            address, address_line1, address_line2, postal_code, campaign,
            assigned_to, accountsIDs, lead_source_id, lead_status_id,
            lead_type_id, contact_type_id, refered_by, serial, role, status,
            social_facebook, social_instagram, social_skype, social_tiktok,
            social_youtube, birthday, custom_fields_data
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
    """
    username = _clean(_pick(payload, "username", "twitter", "x_username"), 255)
    values = (
        lead_id,
        first_name,
        last_name,
        email,
        phone,
        phone,
        _clean(payload.get("personal_email"), 191),
        _clean(payload.get("office_phone"), 191),
        _clean(_pick(payload, "company", "company_name"), 191),
        _clean(_pick(payload, "job_title", "position", "headline"), 191),
        _clean(_pick(payload, "job_title", "position", "headline"), 191),
        _lead_description(payload, meta),
        source,
        username if source in {"twitter", "x"} else _clean(payload.get("twitter"), 255),
        _clean(payload.get("headline") or payload.get("plan_type"), 255),
        _clean(payload.get("website"), 255),
        _clean(payload.get("linkedin_url"), 255),
        username,
        _clean(_pick(payload, "message", "comments", "description"), 500),
        datetime.utcnow(),
        _clean(payload.get("city"), 191),
        _clean(payload.get("country"), 191),
        _clean(payload.get("state"), 191),
        _clean(payload.get("address"), 191),
        _clean(payload.get("address_line1"), 191),
        _clean(payload.get("address_line2"), 191),
        _clean(_pick(payload, "postal_code", "zip"), 191),
        _clean(meta.get("campaign"), 191),
        _clean(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        _clean(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191),
        None,
        None,
        None,
        _clean(os.getenv("CRM_DEFAULT_CONTACT_TYPE_ID"), 191),
        None,
        None,
        "Customer",
        1,
        _clean(payload.get("facebook"), 255),
        _clean(payload.get("instagram"), 255),
        None,
        None,
        None,
        None,
        json.dumps({"meta": meta, "custom_fields": payload.get("custom_fields") or {}}, default=str),
    )
    cursor.execute(sql, values)
    return lead_id


def _link_contact_to_opportunity(cursor, contact_id, opportunity_id):
    cursor.execute(
        """
        INSERT INTO ContactsToOpportunities (contact_id, opportunity_id)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE opportunity_id = VALUES(opportunity_id)
        """,
        (contact_id, opportunity_id),
    )


def _save_pipeline(payload):
    validation_error = _validate(payload)
    if validation_error:
        raise ValueError(validation_error)

    meta = _meta(payload)
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        contact_id = _save_contact(cursor, payload, meta)
        opportunity_id = _save_opportunity(cursor, payload, meta, contact_id)
        _link_contact_to_opportunity(cursor, contact_id, opportunity_id)
        lead_id = _save_lead(cursor, payload, meta)

        conn.commit()
        log_event(
            "Generic landing-page lead saved successfully",
            source=meta["source"],
            external_lead_id=meta["external_id"],
            contact_id=contact_id,
            opportunity_id=opportunity_id,
            lead_id=lead_id,
        )
        return {
            "source_platform": meta["source"],
            "external_lead_id": meta["external_id"],
            "contact_id": contact_id,
            "opportunity_id": opportunity_id,
            "lead_id": lead_id,
        }
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@landing_ingest_bp.route("/leads/submit", methods=["POST", "OPTIONS"])
def submit_landing_lead():
    if request.method == "OPTIONS":
        return _json_response("", 204)

    api_key_error = _require_api_key()
    if api_key_error:
        return api_key_error

    payload = request.get_json(silent=True) or {}
    log_event("Generic landing-page lead received", payload=payload)

    try:
        result = _save_pipeline(payload)
        return _json_response({"success": True, **result}, 201)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        log_event("Generic landing-page lead failed", error=str(exc), payload=payload)
        return _json_response({"success": False, "error": str(exc)}, 500)
