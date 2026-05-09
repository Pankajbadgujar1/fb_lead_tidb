import json
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from datetime import datetime, timezone

import mysql.connector
import requests
from dotenv import load_dotenv

load_dotenv()


def log_event(message, **details):
    payload = {"message": message, **details}
    print(json.dumps(payload, default=str))


def get_connection():
    log_event(
        "Opening TiDB connection",
        host=os.getenv("TIDB_HOST"),
        database=os.getenv("TIDB_DATABASE"),
        port=4000,
    )
    return mysql.connector.connect(
        host=os.getenv("TIDB_HOST"),
        port=4000,
        user=os.getenv("TIDB_USER"),
        password=os.getenv("TIDB_PASSWORD"),
        database=os.getenv("TIDB_DATABASE"),
        ssl_disabled=False,
    )


def ensure_facebook_leads_table(cursor):
    log_event("Ensuring facebook_leads table exists")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS facebook_leads (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            lead_id VARCHAR(100) UNIQUE,
            form_id VARCHAR(100),
            page_id VARCHAR(100),
            ad_id VARCHAR(100),
            full_name VARCHAR(255),
            email VARCHAR(255),
            phone VARCHAR(50),
            raw_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def fetch_lead_from_facebook(lead_id):
    token = os.getenv("FB_PAGE_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/v19.0/{lead_id}"
    params = {"access_token": token}
    log_event("Fetching lead details from Facebook", lead_id=lead_id, url=url)
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise ValueError(f"Facebook API error: {payload['error']}")
    return payload


def _truncate(value, max_length):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:max_length]


def _pick(fields, *names):
    for name in names:
        value = fields.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _normalize_fields(lead_data):
    fields = {}
    for field in lead_data.get("field_data", []):
        name = field.get("name")
        values = field.get("values") or []
        if not name or not values:
            continue
        fields[name] = values[0]
    return fields


def _split_name(full_name, email, phone):
    full_name = (full_name or "").strip()
    if full_name:
        parts = full_name.split()
        if len(parts) == 1:
            return None, parts[0]
        return " ".join(parts[:-1]), parts[-1]

    fallback = email or phone or "Facebook Lead"
    return None, _truncate(fallback, 191)


def _parse_decimal(raw_value):
    if raw_value is None or str(raw_value).strip() == "":
        return Decimal("0")
    cleaned = str(raw_value).replace(",", "").replace("$", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _parse_datetime(raw_value):
    if raw_value is None or str(raw_value).strip() == "":
        return None
    raw_value = str(raw_value).strip()
    if raw_value.endswith("Z"):
        raw_value = raw_value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(
            "Invalid datetime format. Use ISO 8601, for example 2026-04-24T10:30:00"
        ) from exc


def _parse_json_list(raw_value, fallback):
    if raw_value is None:
        return json.dumps(fallback)
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = [raw_value]
    else:
        parsed = raw_value
    return json.dumps(parsed)


def _status_value(raw_value):
    allowed = {"ACTIVE", "INACTIVE", "PENDING", "CLOSED"}
    status = _truncate(raw_value, 191) or "ACTIVE"
    status = status.upper()
    if status not in allowed:
        raise ValueError(f"Invalid status '{raw_value}'. Allowed values: {sorted(allowed)}")
    return status


def _parse_datetime(raw_value):
    if raw_value is None or str(raw_value).strip() == "":
        return None
    raw_value = str(raw_value).strip()
    if raw_value.endswith("Z"):
        raw_value = raw_value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(
            "Invalid datetime format. Use ISO 8601, for example 2026-04-24T10:30:00"
        ) from exc


def _status_value(raw_value):
    allowed = {"ACTIVE", "INACTIVE", "PENDING", "CLOSED"}
    status = _truncate(raw_value, 191) or "ACTIVE"
    status = status.upper()
    if status not in allowed:
        raise ValueError(f"Invalid status '{raw_value}'. Allowed values: {sorted(allowed)}")
    return status


def _contact_record(fields, meta):
    full_name = _pick(fields, "full_name", "name")
    email = _pick(fields, "email", "personal_email")
    phone = _pick(fields, "phone_number", "phone", "mobile_phone")
    first_name, last_name = _split_name(full_name, email, phone)
    default_account_id = _truncate(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191)

    description_parts = [
        f"Facebook lead {meta.get('lead_id')}",
        _pick(fields, "message", "comments", "comment", "description"),
    ]
    description = " | ".join(part for part in description_parts if part)

    return {
        "id": _truncate(f"fb-contact-{meta['lead_id']}", 191),
        "account": default_account_id,
        "assigned_to": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "created_by": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "createdBy": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "updatedBy": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "description": _truncate(description, 191),
        "email": _truncate(email, 191),
        "personal_email": _truncate(_pick(fields, "personal_email"), 191),
        "first_name": _truncate(first_name, 191),
        "last_name": _truncate(last_name or "Lead", 191),
        "office_phone": _truncate(_pick(fields, "office_phone"), 191),
        "mobile_phone": _truncate(phone, 191),
        "website": _truncate(_pick(fields, "website"), 191),
        "position": _truncate(_pick(fields, "position", "job_title"), 191),
        "contact_type_id": _truncate(os.getenv("CRM_DEFAULT_CONTACT_TYPE_ID"), 191),
        "tags": json.dumps(["facebook_lead"]),
        "notes": json.dumps(
            [
                {
                    "source": "facebook_lead_webhook",
                    "lead_id": meta.get("lead_id"),
                    "form_id": meta.get("form_id"),
                    "page_id": meta.get("page_id"),
                    "ad_id": meta.get("ad_id"),
                    "fields": fields,
                }
            ]
        ),
        "accountsIDs": default_account_id,
        "address": _truncate(_pick(fields, "address"), 191),
        "address_line1": _truncate(_pick(fields, "address_line1", "street"), 191),
        "address_line2": _truncate(_pick(fields, "address_line2"), 191),
        "city": _truncate(_pick(fields, "city"), 191),
        "country": _truncate(_pick(fields, "country"), 191),
        "postal_code": _truncate(_pick(fields, "postal_code", "zip"), 191),
        "state": _truncate(_pick(fields, "state"), 191),
    }


def _opportunity_record(fields, meta, contact_id):
    full_name = _pick(fields, "full_name", "name")
    company_name = _pick(fields, "company", "company_name", "business_name")
    opportunity_name = _pick(fields, "opportunity_name", "project_name")
    if not opportunity_name:
        opportunity_name = company_name or full_name or f"Facebook lead {meta['lead_id']}"

    description_parts = [
        f"Created from Facebook lead {meta.get('lead_id')}",
        _pick(fields, "message", "comments", "comment", "description"),
    ]
    description = " | ".join(part for part in description_parts if part)

    currency = _pick(fields, "currency")
    if currency:
        currency = currency.upper()[:3]

    return {
        "id": _truncate(f"fb-opportunity-{meta['lead_id']}", 191),
        "account": _truncate(os.getenv("CRM_DEFAULT_ACCOUNT_ID"), 191),
        "assigned_to": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "budget": _parse_decimal(_pick(fields, "budget")),
        "campaign": _truncate(os.getenv("CRM_DEFAULT_CAMPAIGN_ID"), 191),
        "close_date": None,
        "contact": _truncate(contact_id, 191),
        "created_by": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "createdBy": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "updatedBy": _truncate(os.getenv("CRM_DEFAULT_USER_ID"), 191),
        "currency": _truncate(currency, 3),
        "snapshot_rate": None,
        "description": _truncate(description, 191),
        "expected_revenue": _parse_decimal(_pick(fields, "expected_revenue", "budget")),
        "name": _truncate(opportunity_name, 191),
        "next_step": _truncate(_pick(fields, "next_step"), 191),
        "sales_stage": _truncate(os.getenv("CRM_DEFAULT_SALES_STAGE_ID"), 191),
        "type": _truncate(os.getenv("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"), 191),
        "status": "ACTIVE",
    }


def _manual_contact_record(payload):
    provided_id = _truncate(payload.get("id"), 191)
    email = _truncate(payload.get("email"), 191)
    phone = _truncate(payload.get("mobile_phone") or payload.get("phone"), 191)
    first_name = _truncate(payload.get("first_name"), 191)
    last_name = _truncate(payload.get("last_name"), 191)
    full_name = _truncate(payload.get("full_name") or payload.get("name"), 191)

    if (not first_name or not last_name) and full_name:
        derived_first, derived_last = _split_name(full_name, email, phone)
        first_name = first_name or _truncate(derived_first, 191)
        last_name = last_name or _truncate(derived_last, 191)

    if not last_name:
        raise ValueError("contact.last_name is required")

    generated_id = f"api-contact-{int(datetime.now(timezone.utc).timestamp())}"
    default_account_id = _truncate(
        payload.get("account") or os.getenv("CRM_DEFAULT_ACCOUNT_ID"),
        191,
    )
    default_user_id = _truncate(
        payload.get("assigned_to") or os.getenv("CRM_DEFAULT_USER_ID"),
        191,
    )
    created_by = _truncate(
        payload.get("created_by") or default_user_id,
        191,
    )

    return {
        "id": provided_id or _truncate(generated_id, 191),
        "account": default_account_id,
        "assigned_to": default_user_id,
        "created_by": created_by,
        "createdBy": _truncate(payload.get("createdBy") or created_by, 191),
        "updatedBy": _truncate(
            payload.get("updatedBy") or payload.get("updated_by") or created_by,
            191,
        ),
        "description": _truncate(payload.get("description"), 191),
        "email": email,
        "personal_email": _truncate(payload.get("personal_email"), 191),
        "first_name": first_name,
        "last_name": last_name,
        "office_phone": _truncate(payload.get("office_phone"), 191),
        "mobile_phone": phone,
        "website": _truncate(payload.get("website"), 191),
        "position": _truncate(payload.get("position"), 191),
        "contact_type_id": _truncate(
            payload.get("contact_type_id") or os.getenv("CRM_DEFAULT_CONTACT_TYPE_ID"),
            191,
        ),
        "tags": _parse_json_list(payload.get("tags"), []),
        "notes": _parse_json_list(payload.get("notes"), []),
        "accountsIDs": _truncate(
            payload.get("accountsIDs") or default_account_id,
            191,
        ),
        "address": _truncate(payload.get("address"), 191),
        "address_line1": _truncate(payload.get("address_line1"), 191),
        "address_line2": _truncate(payload.get("address_line2"), 191),
        "city": _truncate(payload.get("city"), 191),
        "country": _truncate(payload.get("country"), 191),
        "postal_code": _truncate(payload.get("postal_code"), 191),
        "state": _truncate(payload.get("state"), 191),
    }


def _manual_opportunity_record(payload, contact_id=None):
    provided_id = _truncate(payload.get("id"), 191)
    generated_id = f"api-opportunity-{int(datetime.now(timezone.utc).timestamp())}"
    name = _truncate(payload.get("name"), 191)
    if not name:
        raise ValueError("opportunity.name is required")

    created_by = _truncate(
        payload.get("created_by") or os.getenv("CRM_DEFAULT_USER_ID"),
        191,
    )

    return {
        "id": provided_id or _truncate(generated_id, 191),
        "account": _truncate(
            payload.get("account") or os.getenv("CRM_DEFAULT_ACCOUNT_ID"),
            191,
        ),
        "assigned_to": _truncate(
            payload.get("assigned_to") or os.getenv("CRM_DEFAULT_USER_ID"),
            191,
        ),
        "budget": _parse_decimal(payload.get("budget")),
        "campaign": _truncate(
            payload.get("campaign") or os.getenv("CRM_DEFAULT_CAMPAIGN_ID"),
            191,
        ),
        "close_date": _parse_datetime(payload.get("close_date")),
        "contact": _truncate(payload.get("contact") or contact_id, 191),
        "created_by": created_by,
        "createdBy": _truncate(payload.get("createdBy") or created_by, 191),
        "updatedBy": _truncate(
            payload.get("updatedBy") or payload.get("updated_by") or created_by,
            191,
        ),
        "currency": _truncate(payload.get("currency"), 3),
        "snapshot_rate": _parse_decimal(payload.get("snapshot_rate"))
        if payload.get("snapshot_rate") not in (None, "")
        else None,
        "description": _truncate(payload.get("description"), 191),
        "expected_revenue": _parse_decimal(
            payload.get("expected_revenue", payload.get("budget"))
        ),
        "name": name,
        "next_step": _truncate(payload.get("next_step"), 191),
        "sales_stage": _truncate(
            payload.get("sales_stage") or os.getenv("CRM_DEFAULT_SALES_STAGE_ID"),
            191,
        ),
        "type": _truncate(
            payload.get("type") or os.getenv("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"),
            191,
        ),
        "status": _status_value(payload.get("status")),
    }


def _manual_opportunity_record(payload):
    provided_id = _truncate(payload.get("id"), 191)
    generated_id = f"api-opportunity-{int(datetime.now(timezone.utc).timestamp())}"
    name = _truncate(payload.get("name"), 191)
    if not name:
        raise ValueError("name is required for opportunity creation")

    return {
        "id": provided_id or _truncate(generated_id, 191),
        "account": _truncate(
            payload.get("account") or os.getenv("CRM_DEFAULT_ACCOUNT_ID"),
            191,
        ),
        "assigned_to": _truncate(
            payload.get("assigned_to") or os.getenv("CRM_DEFAULT_USER_ID"),
            191,
        ),
        "budget": _parse_decimal(payload.get("budget")),
        "campaign": _truncate(
            payload.get("campaign") or os.getenv("CRM_DEFAULT_CAMPAIGN_ID"),
            191,
        ),
        "close_date": _parse_datetime(payload.get("close_date")),
        "contact": _truncate(payload.get("contact"), 191),
        "created_by": _truncate(
            payload.get("created_by") or os.getenv("CRM_DEFAULT_USER_ID"),
            191,
        ),
        "createdBy": _truncate(
            payload.get("createdBy")
            or payload.get("created_by")
            or os.getenv("CRM_DEFAULT_USER_ID"),
            191,
        ),
        "updatedBy": _truncate(
            payload.get("updatedBy")
            or payload.get("updated_by")
            or payload.get("created_by")
            or os.getenv("CRM_DEFAULT_USER_ID"),
            191,
        ),
        "currency": _truncate(payload.get("currency"), 3),
        "snapshot_rate": _parse_decimal(payload.get("snapshot_rate"))
        if payload.get("snapshot_rate") not in (None, "")
        else None,
        "description": _truncate(payload.get("description"), 191),
        "expected_revenue": _parse_decimal(
            payload.get("expected_revenue", payload.get("budget"))
        ),
        "name": name,
        "next_step": _truncate(payload.get("next_step"), 191),
        "sales_stage": _truncate(
            payload.get("sales_stage") or os.getenv("CRM_DEFAULT_SALES_STAGE_ID"),
            191,
        ),
        "type": _truncate(
            payload.get("type") or os.getenv("CRM_DEFAULT_OPPORTUNITY_TYPE_ID"),
            191,
        ),
        "status": _status_value(payload.get("status")),
    }


def _save_facebook_lead(cursor, lead_data, meta, fields):
    sql = """
        INSERT INTO facebook_leads
            (lead_id, form_id, page_id, ad_id, full_name, email, phone, raw_data)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            form_id = VALUES(form_id),
            page_id = VALUES(page_id),
            ad_id = VALUES(ad_id),
            full_name = VALUES(full_name),
            email = VALUES(email),
            phone = VALUES(phone),
            raw_data = VALUES(raw_data)
    """
    values = (
        meta.get("lead_id"),
        meta.get("form_id"),
        meta.get("page_id"),
        meta.get("ad_id"),
        _truncate(_pick(fields, "full_name", "name"), 255),
        _truncate(_pick(fields, "email", "personal_email"), 255),
        _truncate(_pick(fields, "phone_number", "phone", "mobile_phone"), 50),
        json.dumps(lead_data),
    )

    log_event("Saving lead to facebook_leads", lead_id=meta.get("lead_id"))
    cursor.execute(sql, values)


def _save_contact(cursor, record):
    sql = """
        INSERT INTO crm_Contacts (
            id, account, assigned_to, created_by, createdBy, updatedBy, description,
            email, personal_email, first_name, last_name, office_phone, mobile_phone,
            website, position, contact_type_id, tags, notes, accountsIDs, address,
            address_line1, address_line2, city, country, postal_code, state
        ) VALUES (
            %(id)s, %(account)s, %(assigned_to)s, %(created_by)s, %(createdBy)s, %(updatedBy)s,
            %(description)s, %(email)s, %(personal_email)s, %(first_name)s, %(last_name)s,
            %(office_phone)s, %(mobile_phone)s, %(website)s, %(position)s,
            %(contact_type_id)s, %(tags)s, %(notes)s, %(accountsIDs)s, %(address)s,
            %(address_line1)s, %(address_line2)s, %(city)s, %(country)s, %(postal_code)s,
            %(state)s
        )
        ON DUPLICATE KEY UPDATE
            account = VALUES(account),
            assigned_to = VALUES(assigned_to),
            created_by = VALUES(created_by),
            createdBy = VALUES(createdBy),
            updatedBy = VALUES(updatedBy),
            description = VALUES(description),
            email = VALUES(email),
            personal_email = VALUES(personal_email),
            first_name = VALUES(first_name),
            last_name = VALUES(last_name),
            office_phone = VALUES(office_phone),
            mobile_phone = VALUES(mobile_phone),
            website = VALUES(website),
            position = VALUES(position),
            contact_type_id = VALUES(contact_type_id),
            tags = VALUES(tags),
            notes = VALUES(notes),
            accountsIDs = VALUES(accountsIDs),
            address = VALUES(address),
            address_line1 = VALUES(address_line1),
            address_line2 = VALUES(address_line2),
            city = VALUES(city),
            country = VALUES(country),
            postal_code = VALUES(postal_code),
            state = VALUES(state)
    """
    log_event("Saving lead to crm_Contacts", contact_id=record["id"])
    cursor.execute(sql, record)


def _save_opportunity(cursor, record):
    sql = """
        INSERT INTO crm_Opportunities (
            id, account, assigned_to, budget, campaign, close_date, contact,
            created_by, createdBy, updatedBy, currency, snapshot_rate, description,
            expected_revenue, name, next_step, sales_stage, type, status
        ) VALUES (
            %(id)s, %(account)s, %(assigned_to)s, %(budget)s, %(campaign)s, %(close_date)s,
            %(contact)s, %(created_by)s, %(createdBy)s, %(updatedBy)s, %(currency)s,
            %(snapshot_rate)s, %(description)s, %(expected_revenue)s, %(name)s,
            %(next_step)s, %(sales_stage)s, %(type)s, %(status)s
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
            status = VALUES(status)
    """
    log_event("Saving lead to crm_Opportunities", opportunity_id=record["id"])
    cursor.execute(sql, record)


def _link_contact_to_opportunity(cursor, contact_id, opportunity_id):
    sql = """
        INSERT INTO ContactsToOpportunities (contact_id, opportunity_id)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE opportunity_id = VALUES(opportunity_id)
    """
    log_event(
        "Linking contact to opportunity",
        contact_id=contact_id,
        opportunity_id=opportunity_id,
    )
    cursor.execute(sql, (contact_id, opportunity_id))


def save_lead_to_tidb(lead_data, meta):
    fields = _normalize_fields(lead_data)
    contact = _contact_record(fields, meta)
    opportunity = _opportunity_record(fields, meta, contact["id"])

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        ensure_facebook_leads_table(cursor)
        _save_facebook_lead(cursor, lead_data, meta, fields)
        _save_contact(cursor, contact)
        _save_opportunity(cursor, opportunity)
        _link_contact_to_opportunity(cursor, contact["id"], opportunity["id"])
        conn.commit()
        log_event(
            "Lead saved successfully",
            lead_id=meta.get("lead_id"),
            contact_id=contact["id"],
            opportunity_id=opportunity["id"],
        )
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        log_event(
            "Failed to save lead to TiDB",
            lead_id=meta.get("lead_id"),
            error=str(exc),
            lead_data=lead_data,
        )
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def save_opportunity_to_tidb(payload):
    record = _manual_opportunity_record(payload)

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        _save_opportunity(cursor, record)
        conn.commit()
        log_event("Opportunity saved successfully", opportunity_id=record["id"])
        return record
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        log_event(
            "Failed to save opportunity to TiDB",
            opportunity_id=record.get("id"),
            error=str(exc),
            payload=payload,
        )
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def extract_leadgen_events(payload):
    events = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue

            lead_value = change.get("value", {})
            meta = {
                "lead_id": lead_value.get("leadgen_id"),
                "form_id": lead_value.get("form_id"),
                "page_id": lead_value.get("page_id"),
                "ad_id": lead_value.get("ad_id"),
            }
            if not meta["lead_id"]:
                raise ValueError("leadgen_id missing from webhook payload")
            events.append(meta)
    return events


def process_webhook_payload(payload):
    lead_events = extract_leadgen_events(payload)
    if not lead_events:
        return []

    processed = []
    for meta in lead_events:
        lead_details = fetch_lead_from_facebook(meta["lead_id"])
        save_lead_to_tidb(lead_details, meta)
        processed.append(meta)

    return processed


def save_opportunity_to_tidb(payload):
    record = _manual_opportunity_record(payload)

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        _save_opportunity(cursor, record)
        conn.commit()
        log_event("Opportunity saved successfully", opportunity_id=record["id"])
        return record
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        log_event(
            "Failed to save opportunity to TiDB",
            opportunity_id=record.get("id"),
            error=str(exc),
            payload=payload,
        )
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def save_contact_and_opportunity_to_tidb(payload):
    contact_payload = payload.get("contact") or {}
    opportunity_payload = payload.get("opportunity") or {}

    if not contact_payload:
        raise ValueError("contact object is required")
    if not opportunity_payload:
        raise ValueError("opportunity object is required")

    contact_record = _manual_contact_record(contact_payload)
    opportunity_record = _manual_opportunity_record(
        opportunity_payload, contact_id=contact_record["id"]
    )

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        _save_contact(cursor, contact_record)
        _save_opportunity(cursor, opportunity_record)
        _link_contact_to_opportunity(
            cursor, contact_record["id"], opportunity_record["id"]
        )
        conn.commit()
        log_event(
            "Contact and opportunity saved successfully",
            contact_id=contact_record["id"],
            opportunity_id=opportunity_record["id"],
        )
        return {
            "contact": contact_record,
            "opportunity": opportunity_record,
        }
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        log_event(
            "Failed to save contact and opportunity to TiDB",
            error=str(exc),
            payload=payload,
        )
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
