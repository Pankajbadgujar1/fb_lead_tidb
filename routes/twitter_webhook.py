"""
X (Twitter) Lead Ads webhook route.

Endpoint:  /api/twitter/webhook
  GET  → CRC challenge response (X verifies your endpoint)
  POST → Receive lead → fetch from X Ads API → save into existing TiDB tables

Tables used (NO new tables created):
  1. crm_Contacts             — social_twitter stores X handle
  2. crm_Opportunities        — source='twitter', ad_id, form_id, raw_data
  3. crm_Leads                — source_platform='twitter', twitter column
  4. ContactsToOpportunities  — link (reuses _link_contact_to_opportunity)
"""

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime

import requests
from flask import Blueprint, request

from crm_sync import (
    _truncate,
    _pick,
    _normalize_fields,
    _link_contact_to_opportunity,
    get_connection,
    log_event,
)

twitter_bp = Blueprint("twitter_webhook", __name__, url_prefix="/api/twitter")


# ─────────────────────────────────────────────────────────────────
# Signature verification
# ─────────────────────────────────────────────────────────────────

def _verify_twitter_signature(req):
    """
    X sends: x-twitter-webhooks-signature: sha256=<base64_hmac>
    Verified using X_CONSUMER_SECRET from .env
    """
    secret = os.getenv("X_CONSUMER_SECRET", "").encode("utf-8")
    sig_header = req.headers.get("x-twitter-webhooks-signature", "")
    if not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + base64.b64encode(
        hmac.new(secret, req.data, hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(sig_header, expected)


# ─────────────────────────────────────────────────────────────────
# Fetch lead from X Ads API
# ─────────────────────────────────────────────────────────────────

def _fetch_lead_from_x(lead_id, ad_account_id):
    """
    GET /9/accounts/{account_id}/leads/{lead_id}
    Returns normalised dict with field_data list — same shape _normalize_fields() expects.
    """
    use_mock_leads = os.getenv("X_USE_MOCK_LEADS", "false").lower() == "true"
    is_test_lead = str(lead_id).startswith("test_lead_")
    if use_mock_leads or is_test_lead:
        log_event(
            "Using mock X lead data",
            lead_id=lead_id,
            ad_account_id=ad_account_id,
            reason="X_USE_MOCK_LEADS" if use_mock_leads else "test_lead_id",
        )
        return {
            "id": lead_id,
            "field_data": [
                {"name": "full_name", "values": ["Pankaj Test"]},
                {"name": "email", "values": [f"{lead_id}@example.com"]},
                {"name": "phone_number", "values": ["+919876543210"]},
                {"name": "city", "values": ["Pune"]},
                {"name": "country", "values": ["India"]},
                {"name": "company", "values": ["Test Company Pvt Ltd"]},
                {"name": "job_title", "values": ["Marketing Manager"]},
                {"name": "message", "values": ["Mock X lead for deployment testing"]},
            ],
            "raw": {"mock": True},
        }

    bearer = os.getenv("X_BEARER_TOKEN", "")
    url = f"https://ads-api.twitter.com/9/accounts/{ad_account_id}/leads/{lead_id}"
    headers = {"Authorization": f"Bearer {bearer}"}

    log_event("Fetching lead from X Ads API", lead_id=lead_id, url=url)
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("errors"):
        raise ValueError(f"X Ads API error: {data['errors']}")

    raw = data.get("data", {})

    # Normalise into field_data list — same shape _normalize_fields() expects
    field_data = []
    for key, val in raw.items():
        if key in ("id", "created_at"):
            continue
        field_data.append({
            "name": key,
            "values": [val] if not isinstance(val, list) else val,
        })

    return {"id": lead_id, "field_data": field_data, "raw": raw}


# ─────────────────────────────────────────────────────────────────
# Save to crm_Contacts
# Exact columns from your SHOW CREATE TABLE crm_Contacts
# ─────────────────────────────────────────────────────────────────

def _save_twitter_to_contacts(cursor, fields, meta):
    full_name  = _pick(fields, "full_name", "name") or ""
    parts      = full_name.strip().split()
    first_name = _truncate(parts[0], 191) if parts else "Unknown"
    last_name  = _truncate(" ".join(parts[1:]), 191) if len(parts) > 1 else "Lead"

    x_handle   = _truncate(meta.get("x_username") or _pick(fields, "username", "twitter_username"), 191)
    email      = _truncate(_pick(fields, "email", "personal_email"), 191)
    phone      = _truncate(_pick(fields, "phone_number", "phone", "mobile_phone"), 191)

    description_parts = [
        f"Twitter/X lead {meta.get('lead_id')}",
        _pick(fields, "message", "comments", "description"),
    ]
    description = _truncate(" | ".join(p for p in description_parts if p), 191)

    contact_id = _truncate(f"tw-contact-{meta['lead_id']}", 191)

    sql = """
        INSERT INTO crm_Contacts (
            id, first_name, last_name,
            email, personal_email, mobile_phone, office_phone, phone,
            social_twitter, social_facebook, social_linkedin,
            social_skype, social_instagram, social_youtube, social_tiktok,
            city, country, state,
            address, address_line1, address_line2, postal_code,
            company, jobTitle, position, website,
            account, accountsIDs, assigned_to,
            created_by, createdBy, updatedBy,
            contact_type_id, description, campaign,
            tags, notes,
            birthday, role, status,
            lead_source_id, lead_status_id, lead_type_id,
            refered_by, serial, custom_fields_data
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            email          = VALUES(email),
            mobile_phone   = VALUES(mobile_phone),
            phone          = VALUES(phone),
            social_twitter = VALUES(social_twitter),
            description    = VALUES(description),
            city           = VALUES(city),
            country        = VALUES(country),
            company        = VALUES(company),
            jobTitle       = VALUES(jobTitle),
            notes          = VALUES(notes),
            updatedBy      = VALUES(updatedBy)
    """

    default_account_id  = _truncate(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191)
    default_user_id     = _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191)
    contact_type_id     = _truncate(os.getenv("CRM_DEFAULT_CONTACT_TYPE_ID"), 191)

    values = (
        contact_id,
        first_name, last_name,
        email, None, phone, None, phone,                      # email, personal_email, mobile_phone, office_phone, phone
        x_handle, None, None, None, None, None, None,         # social_twitter … social_tiktok
        _truncate(_pick(fields, "city"), 191),
        _truncate(_pick(fields, "country"), 191),
        _truncate(_pick(fields, "state"), 191),
        _truncate(_pick(fields, "address"), 191),
        None, None,                                            # address_line1, address_line2
        _truncate(_pick(fields, "postal_code", "zip"), 191),
        _truncate(_pick(fields, "company", "company_name"), 191),
        _truncate(_pick(fields, "job_title", "position"), 191),
        _truncate(_pick(fields, "job_title", "position"), 191),
        _truncate(_pick(fields, "website"), 191),
        default_account_id, default_account_id, default_user_id,   # account, accountsIDs, assigned_to
        default_user_id, default_user_id, default_user_id,         # created_by, createdBy, updatedBy
        contact_type_id,
        description,
        _truncate(meta.get("campaign_id"), 191),
        json.dumps(["twitter_lead"]),
        json.dumps([{
            "source":      "twitter_lead_webhook",
            "lead_id":     meta.get("lead_id"),
            "tweet_id":    meta.get("tweet_id"),
            "card_id":     meta.get("card_id"),
            "campaign_id": meta.get("campaign_id"),
            "account_id":  meta.get("account_id"),
            "fields":      fields,
        }]),
        None, "Customer", 1,                                   # birthday, role, status
        None, None, None,                                      # lead_source_id, lead_status_id, lead_type_id
        None, None, None,                                      # refered_by, serial, custom_fields_data
    )

    log_event("Saving Twitter lead to crm_Contacts", contact_id=contact_id)
    cursor.execute(sql, values)
    return contact_id


# ─────────────────────────────────────────────────────────────────
# Save to crm_Opportunities
# Exact columns from your SHOW CREATE TABLE crm_Opportunities
# ─────────────────────────────────────────────────────────────────

def _save_twitter_to_opportunities(cursor, fields, meta, contact_id):
    full_name    = _pick(fields, "full_name", "name")
    company_name = _pick(fields, "company", "company_name", "business_name")
    opp_name     = _truncate(company_name or full_name or f"Twitter/X lead {meta['lead_id']}", 191)

    description_parts = [
        f"Created from Twitter/X lead {meta.get('lead_id')}",
        _pick(fields, "message", "comments", "description"),
    ]
    description  = _truncate(" | ".join(p for p in description_parts if p), 191)
    opp_id       = _truncate(f"tw-opportunity-{meta['lead_id']}", 191)

    sql = """
        INSERT INTO crm_Opportunities (
            id, name, account, assigned_to,
            created_by, createdBy, updatedBy,
            contact, campaign, sales_stage, type, status,
            description, budget, expected_revenue,
            currency, snapshot_rate, close_date, next_step,
            source, ad_id, form_id,
            email, phone, city,
            raw_data, clientName, category, custom_fields_data
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            name        = VALUES(name),
            source      = VALUES(source),
            ad_id       = VALUES(ad_id),
            form_id     = VALUES(form_id),
            email       = VALUES(email),
            phone       = VALUES(phone),
            city        = VALUES(city),
            raw_data    = VALUES(raw_data),
            description = VALUES(description),
            updatedBy   = VALUES(updatedBy)
    """

    default_account_id   = _truncate(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191)
    default_user_id      = _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191)
    default_campaign_id  = _truncate(os.getenv("CRM_DEFAULT_CAMPAIGN_ID"), 191)
    default_sales_stage  = _truncate(os.getenv("CRM_DEFAULT_SALES_STAGE_ID"), 191)
    default_opp_type     = _truncate(os.getenv("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"), 191)

    values = (
        opp_id, opp_name, default_account_id, default_user_id,
        default_user_id, default_user_id, default_user_id,
        contact_id, default_campaign_id, default_sales_stage, default_opp_type, "ACTIVE",
        description, 0, 0,
        None, None, None, None,
        # Twitter-specific existing columns
        "twitter",                                             # source
        _truncate(meta.get("card_id"), 100),                  # ad_id  ← card_id
        _truncate(meta.get("campaign_id"), 100),               # form_id ← campaign_id
        _truncate(_pick(fields, "email"), 255),
        _truncate(_pick(fields, "phone_number", "phone", "mobile_phone"), 50),
        _truncate(_pick(fields, "city"), 100),
        json.dumps({
            "lead_id":     meta.get("lead_id"),
            "tweet_id":    meta.get("tweet_id"),
            "card_id":     meta.get("card_id"),
            "campaign_id": meta.get("campaign_id"),
            "account_id":  meta.get("account_id"),
            "fields":      fields,
        }),
        _truncate(full_name, 191),                             # clientName
        None, None,                                            # category, custom_fields_data
    )

    log_event("Saving Twitter lead to crm_Opportunities", opportunity_id=opp_id)
    cursor.execute(sql, values)
    return opp_id


# ─────────────────────────────────────────────────────────────────
# Save to crm_Leads
# Exact columns from your SHOW CREATE TABLE crm_Leads
# ─────────────────────────────────────────────────────────────────

def _save_twitter_to_leads(cursor, fields, meta):
    full_name  = _pick(fields, "full_name", "name") or ""
    parts      = full_name.strip().split()
    first_name = _truncate(parts[0], 191) if parts else "Unknown"
    last_name  = _truncate(" ".join(parts[1:]), 191) if len(parts) > 1 else None

    x_handle   = _truncate(meta.get("x_username") or _pick(fields, "username", "twitter_username"), 255)
    phone      = _truncate(_pick(fields, "phone_number", "phone", "mobile_phone"), 191)
    lead_id    = str(uuid.uuid4())

    sql = """
        INSERT INTO crm_Leads (
            id, firstName, lastName,
            email, phone, mobile_phone, personal_email, office_phone,
            company, jobTitle, position, description,
            source_platform, twitter, headline, website, linkedin_url,
            username, message_snippet, message_date,
            city, country, state,
            address, address_line1, address_line2, postal_code,
            campaign, assigned_to, accountsIDs,
            lead_source_id, lead_status_id, lead_type_id, contact_type_id,
            refered_by, serial, role, status,
            social_facebook, social_instagram, social_skype,
            social_tiktok, social_youtube,
            birthday, custom_fields_data
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s
        )
    """

    values = (
        lead_id, first_name, last_name,
        _truncate(_pick(fields, "email", "personal_email"), 191),
        phone, phone, None, None,
        _truncate(_pick(fields, "company", "company_name"), 191),
        _truncate(_pick(fields, "job_title", "position"), 191),
        _truncate(_pick(fields, "job_title", "position"), 191),
        _truncate(f"Twitter/X lead {meta.get('lead_id')}", 191),
        "twitter",                                             # source_platform
        x_handle,                                             # twitter column = X handle
        None,                                                  # headline
        _truncate(_pick(fields, "website"), 255),
        None,                                                  # linkedin_url
        x_handle,                                             # username
        _truncate(_pick(fields, "message", "comments"), 500), # message_snippet
        datetime.utcnow(),                                     # message_date
        _truncate(_pick(fields, "city"), 191),
        _truncate(_pick(fields, "country"), 191),
        _truncate(_pick(fields, "state"), 191),
        _truncate(_pick(fields, "address"), 191),
        None, None,                                            # address_line1, address_line2
        _truncate(_pick(fields, "postal_code", "zip"), 191),
        _truncate(meta.get("campaign_id"), 191),               # campaign
        None, None,                                            # assigned_to, accountsIDs
        None, None, None, None,                                # lead_source_id … contact_type_id
        None, None, "Customer", 1,                             # refered_by, serial, role, status
        None, None, None,                                      # social_facebook, social_instagram, social_skype
        None, None,                                            # social_tiktok, social_youtube
        None, None,                                            # birthday, custom_fields_data
    )

    log_event("Saving Twitter lead to crm_Leads", lead_id=lead_id)
    cursor.execute(sql, values)
    return lead_id


# ─────────────────────────────────────────────────────────────────
# Parse incoming X webhook payload
# ─────────────────────────────────────────────────────────────────

def _extract_twitter_lead_events(payload):
    """
    Handles both X payload shapes:
    Shape 1 — Lead Generation Card via DM events (older format)
    Shape 2 — Ads API lead_generation_card_events (newer format)
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}

    if not isinstance(payload, dict):
        payload = {}

    events = []

    # Shape 1: direct_message_events (Lead Gen Card)
    for dm in payload.get("direct_message_events", []):
        msg     = dm.get("message_create", {}).get("message_data", {})
        card    = msg.get("attachment", {}).get("card", {})
        if not card:
            continue
        binding = card.get("binding_values", {})
        lead_id = (
            binding.get("lead_id", {}).get("string_value")
            or binding.get("user_data_lead_id", {}).get("string_value")
        )
        if not lead_id:
            continue
        events.append({
            "lead_id":     lead_id,
            "tweet_id":    dm.get("id"),
            "card_id":     card.get("id"),
            "campaign_id": binding.get("campaign_id", {}).get("string_value"),
            "account_id":  os.getenv("X_AD_ACCOUNT_ID", ""),
            "x_username":  None,
        })

    # Shape 2: lead_generation_card_events (Ads API)
    for event in payload.get("lead_generation_card_events", []):
        lead_id = event.get("lead_id")
        if not lead_id:
            continue
        events.append({
            "lead_id":     str(lead_id),
            "tweet_id":    event.get("tweet_id"),
            "card_id":     event.get("card_id"),
            "campaign_id": event.get("campaign_id"),
            "account_id":  event.get("account_id") or os.getenv("X_AD_ACCOUNT_ID", ""),
            "x_username":  event.get("username"),
        })

    return events


# ─────────────────────────────────────────────────────────────────
# Full pipeline
# ─────────────────────────────────────────────────────────────────

def _process_twitter_lead(meta):
    """
    Saves one X lead into:
      crm_Contacts → crm_Opportunities → ContactsToOpportunities → crm_Leads
    Zero new tables created.
    """
    lead_data = _fetch_lead_from_x(meta["lead_id"], meta["account_id"])
    fields    = _normalize_fields(lead_data)

    conn   = None
    cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor()

        contact_id = _save_twitter_to_contacts(cursor, fields, meta)
        opp_id     = _save_twitter_to_opportunities(cursor, fields, meta, contact_id)
        _link_contact_to_opportunity(cursor, contact_id, opp_id)
        crm_lead_id = _save_twitter_to_leads(cursor, fields, meta)

        conn.commit()
        log_event(
            "Twitter lead saved successfully",
            lead_id=meta.get("lead_id"),
            contact_id=contact_id,
            opportunity_id=opp_id,
            crm_lead_id=crm_lead_id,
        )
    except Exception as exc:
        if conn:
            conn.rollback()
        log_event(
            "Failed to save Twitter lead",
            lead_id=meta.get("lead_id"),
            error=str(exc),
        )
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return meta


# ─────────────────────────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────────────────────────

def _clean_form_value(value, max_length=500):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:max_length]


def _form_fields_to_lead_data(fields):
    field_data = []
    for key, value in fields.items():
        cleaned = _clean_form_value(value)
        if cleaned is None:
            continue
        field_data.append({"name": key, "values": [cleaned]})
    return {
        "field_data": field_data,
        "raw": {"source": "twitter_form_submit", "fields": fields},
    }


def _extract_direct_form_payload(payload):
    if not isinstance(payload, dict):
        payload = {}

    event = {}
    events = payload.get("lead_generation_card_events")
    if isinstance(events, list) and events:
        event = events[0] or {}

    raw_fields = payload.get("field_data") or event.get("field_data") or {}
    if isinstance(raw_fields, list):
        fields = _normalize_fields({"field_data": raw_fields})
    elif isinstance(raw_fields, dict):
        fields = dict(raw_fields)
    else:
        fields = {}

    direct_field_names = [
        "full_name",
        "name",
        "email",
        "phone",
        "phone_number",
        "age",
        "gender",
        "smoker",
        "plan_type",
        "coverage",
        "income",
        "message",
        "city",
        "country",
        "company",
        "job_title",
    ]
    for name in direct_field_names:
        if name in payload and name not in fields:
            fields[name] = payload.get(name)

    if fields.get("phone") and not fields.get("phone_number"):
        fields["phone_number"] = fields.get("phone")
    if fields.get("name") and not fields.get("full_name"):
        fields["full_name"] = fields.get("name")

    utm_source = _clean_form_value(payload.get("utm_source") or "twitter", 100)
    utm_medium = _clean_form_value(payload.get("utm_medium") or "paid", 100)
    utm_campaign = _clean_form_value(
        payload.get("utm_campaign") or event.get("campaign_id") or "life-insurance",
        191,
    )
    twclid = _clean_form_value(payload.get("twclid") or event.get("tweet_id"), 191)

    if not fields.get("message"):
        message_parts = [
            "Life insurance lead",
            f"Plan: {fields.get('plan_type') or 'N/A'}",
            f"Coverage: {fields.get('coverage') or 'N/A'}",
            f"Age: {fields.get('age') or 'N/A'}",
            f"Smoker: {fields.get('smoker') or 'N/A'}",
            f"UTM: {utm_source}/{utm_medium}/{utm_campaign}",
        ]
        if twclid:
            message_parts.append(f"twclid: {twclid}")
        fields["message"] = " | ".join(message_parts)

    meta = {
        "lead_id": _clean_form_value(payload.get("lead_id") or event.get("lead_id"), 100)
        or f"tw-form-{uuid.uuid4()}",
        "tweet_id": twclid,
        "card_id": _clean_form_value(
            payload.get("card_id") or event.get("card_id") or utm_campaign,
            100,
        ),
        "campaign_id": utm_campaign,
        "account_id": _clean_form_value(
            payload.get("account_id")
            or event.get("account_id")
            or os.getenv("X_AD_ACCOUNT_ID", ""),
            100,
        ),
        "x_username": _clean_form_value(payload.get("username") or event.get("username"), 191),
    }
    return fields, meta


def _validate_direct_form_fields(fields):
    full_name = _clean_form_value(fields.get("full_name") or fields.get("name"), 191)
    email = _clean_form_value(fields.get("email"), 191)
    phone = _clean_form_value(fields.get("phone_number") or fields.get("phone"), 50)
    age = _clean_form_value(fields.get("age"), 10)

    if not full_name:
        return "full_name is required."
    if not phone:
        return "phone is required."
    if not email or "@" not in email:
        return "valid email is required."
    if age:
        try:
            if int(age) < 18:
                return "age must be 18 or above."
        except ValueError:
            return "age must be a number."
    return None


def _process_direct_twitter_form(payload):
    fields, meta = _extract_direct_form_payload(payload)
    error = _validate_direct_form_fields(fields)
    if error:
        raise ValueError(error)

    lead_data = _form_fields_to_lead_data(fields)
    normalized_fields = _normalize_fields(lead_data)

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        contact_id = _save_twitter_to_contacts(cursor, normalized_fields, meta)
        opp_id = _save_twitter_to_opportunities(cursor, normalized_fields, meta, contact_id)
        _link_contact_to_opportunity(cursor, contact_id, opp_id)
        crm_lead_id = _save_twitter_to_leads(cursor, normalized_fields, meta)

        conn.commit()
        log_event(
            "Twitter direct form lead saved successfully",
            lead_id=meta.get("lead_id"),
            contact_id=contact_id,
            opportunity_id=opp_id,
            crm_lead_id=crm_lead_id,
        )
        return {
            "lead_id": meta.get("lead_id"),
            "contact_id": contact_id,
            "opportunity_id": opp_id,
            "crm_lead_id": crm_lead_id,
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        log_event(
            "Failed to save Twitter direct form lead",
            lead_id=meta.get("lead_id"),
            error=str(exc),
        )
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@twitter_bp.route("/form-submit", methods=["POST"])
def twitter_form_submit():
    data = request.get_json(silent=True) or {}
    log_event("Twitter direct form POST received", payload=data)

    try:
        result = _process_direct_twitter_form(data)
        return {"success": True, **result}, 201
    except ValueError as exc:
        return {"success": False, "error": str(exc)}, 400
    except Exception as exc:
        log_event("Twitter direct form processing failed", error=str(exc), payload=data)
        return {"success": False, "error": str(exc)}, 500


@twitter_bp.route("/webhook", methods=["GET", "POST"])
def twitter_webhook():

    # ── GET: CRC challenge (X verifies your server) ───────────────
    if request.method == "GET":
        crc_token = request.args.get("crc_token", "")
        secret    = os.getenv("X_CONSUMER_SECRET", "").encode("utf-8")
        digest    = hmac.new(secret, crc_token.encode("utf-8"), hashlib.sha256).digest()
        log_event("X CRC challenge responded", crc_token=crc_token)
        return {"response_token": "sha256=" + base64.b64encode(digest).decode("utf-8")}

    # ── POST: incoming lead event ─────────────────────────────────
    if os.getenv("X_VERIFY_SIGNATURE", "true").lower() == "true":
        if not _verify_twitter_signature(request):
            log_event("X webhook signature verification failed")
            return {"error": "Forbidden"}, 403

    data = request.get_json(silent=True) or {}
    log_event("X Webhook POST received", payload=data)

    try:
        events = _extract_twitter_lead_events(data)
        if not events:
            return {"message": "Not a lead event", "processed": 0}

        processed = []
        for meta in events:
            _process_twitter_lead(meta)
            processed.append(meta)

        return {"success": True, "processed": len(processed), "leads": processed}

    except Exception as exc:
        log_event("X Webhook processing failed", error=str(exc), payload=data)
        return {"error": str(exc)}, 500 
