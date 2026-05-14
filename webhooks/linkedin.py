import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from crm_sync import (
    _link_contact_to_opportunity,
    _pick,
    _save_contact,
    _save_opportunity,
    _truncate,
    get_connection,
    log_event,
)


linkedin_bp = Blueprint("linkedin", __name__)


FIELD_MAP = {
    "firstName": "first_name",
    "first_name": "first_name",
    "lastName": "last_name",
    "last_name": "last_name",
    "emailAddress": "email",
    "email": "email",
    "phoneNumber": "phone_number",
    "phone": "phone_number",
    "companyName": "company",
    "company": "company",
    "jobTitle": "job_title",
    "job_title": "job_title",
    "city": "city",
    "country": "country",
    "state": "state",
    "website": "website",
    "message": "message",
}


def _client_secret():
    return os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()


def _signature(secret, payload):
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _signature_matches(raw_payload, header_value):
    secret = _client_secret()
    if not secret:
        log_event("LinkedIn client secret missing")
        return False

    header_value = (header_value or "").strip()
    expected = _signature(secret, raw_payload)
    return any(
        hmac.compare_digest(header_value, candidate)
        for candidate in (expected, f"sha256={expected}")
    )


def _first_value(value):
    if isinstance(value, list):
        return _first_value(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("value", "text", "localized", "string", "name"):
            if value.get(key):
                return value.get(key)
        return json.dumps(value, default=str)
    return value


def _normalize_field_values(payload):
    fields = {}
    field_values = payload.get("fieldValues") or payload.get("field_values") or []

    if isinstance(field_values, dict):
        field_values = [
            {"question": key, "values": value}
            for key, value in field_values.items()
        ]

    for item in field_values:
        if not isinstance(item, dict):
            continue
        key = item.get("question") or item.get("name") or item.get("field") or item.get("key")
        value = item.get("values", item.get("value"))
        normalized_key = FIELD_MAP.get(str(key), str(key)) if key else None
        normalized_value = _first_value(value)
        if normalized_key and normalized_value is not None:
            fields[normalized_key] = str(normalized_value).strip()

    for key, value in payload.items():
        if key in FIELD_MAP and value is not None:
            fields[FIELD_MAP[key]] = str(value).strip()

    return {key: value for key, value in fields.items() if value}


def _extract_payloads(payload):
    if not isinstance(payload, dict):
        return []

    for key in ("events", "notifications", "data", "elements"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return [payload]


def _lead_urn(payload):
    return (
        payload.get("leadGenFormResponse")
        or payload.get("leadGenFormResponseUrn")
        or payload.get("lead_gen_form_response")
        or payload.get("id")
        or payload.get("lead_id")
        or f"linkedin-{uuid.uuid4()}"
    )


def _clean_urn(value, fallback_prefix):
    cleaned = _truncate(str(value).replace(":", "-").replace("/", "-"), 120)
    return cleaned or f"{fallback_prefix}-{uuid.uuid4()}"


def _contact_record(fields, meta):
    first_name = _truncate(_pick(fields, "first_name"), 191)
    last_name = _truncate(_pick(fields, "last_name"), 191)
    email = _truncate(_pick(fields, "email"), 191)
    phone = _truncate(_pick(fields, "phone_number", "phone"), 191)

    if not first_name and not last_name:
        first_name = "LinkedIn"
        last_name = "Lead"
    elif not last_name:
        last_name = "Lead"

    default_account_id = _truncate(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191)
    default_user_id = _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191)
    lead_urn = meta["lead_urn"]

    return {
        "id": _truncate(f"li-contact-{_clean_urn(lead_urn, 'lead')}", 191),
        "account": default_account_id,
        "assigned_to": default_user_id,
        "created_by": default_user_id,
        "createdBy": default_user_id,
        "updatedBy": default_user_id,
        "description": _truncate(f"LinkedIn lead {lead_urn}", 191),
        "email": email,
        "personal_email": None,
        "first_name": first_name,
        "last_name": last_name,
        "office_phone": None,
        "mobile_phone": phone,
        "website": _truncate(_pick(fields, "website"), 191),
        "position": _truncate(_pick(fields, "job_title"), 191),
        "contact_type_id": _truncate(os.getenv("CRM_DEFAULT_CONTACT_TYPE_ID"), 191),
        "tags": json.dumps(["linkedin_lead"]),
        "notes": json.dumps(
            [{
                "source": "linkedin_webhook",
                "lead_urn": lead_urn,
                "form_urn": meta.get("form_urn"),
                "occurred_at": meta.get("occurred_at"),
                "fields": fields,
            }]
        ),
        "accountsIDs": default_account_id,
        "address": None,
        "address_line1": None,
        "address_line2": None,
        "city": _truncate(_pick(fields, "city"), 191),
        "country": _truncate(_pick(fields, "country"), 191),
        "postal_code": None,
        "state": _truncate(_pick(fields, "state"), 191),
    }


def _opportunity_record(fields, meta, contact_id):
    full_name = " ".join(
        part for part in [_pick(fields, "first_name"), _pick(fields, "last_name")] if part
    ).strip()
    company = _pick(fields, "company", "company_name")
    lead_urn = meta["lead_urn"]
    name = company or full_name or f"LinkedIn lead {lead_urn}"
    default_user_id = _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191)

    return {
        "id": _truncate(f"li-opportunity-{_clean_urn(lead_urn, 'lead')}", 191),
        "account": _truncate(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191),
        "assigned_to": default_user_id,
        "budget": 0,
        "campaign": _truncate(os.getenv("CRM_DEFAULT_CAMPAIGN_ID"), 191),
        "close_date": None,
        "contact": _truncate(contact_id, 191),
        "created_by": default_user_id,
        "createdBy": default_user_id,
        "updatedBy": default_user_id,
        "currency": None,
        "snapshot_rate": None,
        "description": _truncate(
            " | ".join(
                part
                for part in [f"Created from LinkedIn lead {lead_urn}", _pick(fields, "message")]
                if part
            ),
            191,
        ),
        "expected_revenue": 0,
        "name": _truncate(name, 191),
        "next_step": _truncate(_pick(fields, "email", "phone_number"), 191),
        "sales_stage": _truncate(os.getenv("CRM_DEFAULT_SALES_STAGE_ID"), 191),
        "type": _truncate(os.getenv("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"), 191),
        "status": "ACTIVE",
    }


def _save_linkedin_lead(fields, meta):
    conn = None
    cursor = None
    contact = _contact_record(fields, meta)
    opportunity = _opportunity_record(fields, meta, contact["id"])

    try:
        conn = get_connection()
        cursor = conn.cursor()
        _save_contact(cursor, contact)
        _save_opportunity(cursor, opportunity)
        _link_contact_to_opportunity(cursor, contact["id"], opportunity["id"])
        conn.commit()
        log_event(
            "LinkedIn lead saved successfully",
            lead_urn=meta.get("lead_urn"),
            contact_id=contact["id"],
            opportunity_id=opportunity["id"],
        )
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        log_event("Failed to save LinkedIn lead", lead_urn=meta.get("lead_urn"), error=str(exc))
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    return {
        "lead_urn": meta.get("lead_urn"),
        "contact_id": contact["id"],
        "opportunity_id": opportunity["id"],
    }


@linkedin_bp.route("/webhook/linkedin", methods=["GET", "POST"])
def linkedin_webhook():
    if request.method == "GET":
        challenge_code = request.args.get("challengeCode")
        secret = _client_secret()

        if not challenge_code:
            return jsonify({"error": "No challenge code"}), 400
        if not secret:
            return jsonify({"error": "LINKEDIN_CLIENT_SECRET is not configured"}), 500

        return jsonify({
            "challengeCode": challenge_code,
            "challengeResponse": _signature(secret, challenge_code.encode("utf-8")),
        }), 200

    raw_payload = request.get_data() or b""
    signature_header = request.headers.get("X-LI-Signature", "")
    verify_signature = os.getenv("LINKEDIN_VERIFY_SIGNATURE", "true").lower() == "true"

    if verify_signature and not _signature_matches(raw_payload, signature_header):
        return jsonify({"error": "Invalid signature"}), 403

    payload = request.get_json(silent=True) or {}
    log_event("LinkedIn webhook POST received", payload=payload)

    try:
        processed = []
        for item in _extract_payloads(payload):
            fields = _normalize_field_values(item)
            meta = {
                "lead_urn": _lead_urn(item),
                "form_urn": item.get("leadGenForm") or item.get("leadGenFormUrn"),
                "occurred_at": item.get("occurredAt") or item.get("createdAt"),
                "received_at": datetime.utcnow().isoformat(),
            }
            processed.append(_save_linkedin_lead(fields, meta))

        return jsonify({"success": True, "processed": len(processed), "leads": processed}), 200
    except Exception as exc:
        log_event("LinkedIn webhook processing failed", error=str(exc), payload=payload)
        return jsonify({"success": False, "error": str(exc)}), 500
