"""Facebook Conversions API helpers for CRM lifecycle events."""

import hashlib
import os
import time

import requests

from crm_sync import log_event


PIXEL_ID = os.environ.get("FB_CAPI_PIXEL_ID", "960269016759356")
ACCESS_TOKEN = os.environ.get("FB_CAPI_ACCESS_TOKEN")
GRAPH_API_VERSION = os.environ.get("FB_CAPI_GRAPH_VERSION", "v19.0")
ACTION_SOURCE = os.environ.get("FB_CAPI_ACTION_SOURCE", "system_generated")


STAGE_EVENT_MAP = {
    "8a9353e7-fe51-47fc-9db7-f495d7a6f5ec": {
        "event_name": "Lead",
        "stage_name": "New Lead Intake",
    },
    "26939e8f-768a-47bd-b5c2-b2da1c96065a": {
        "event_name": "Lead",
        "stage_name": "Marketing Qualified Leads",
        "custom_data": {"lead_quality": "MQL"},
    },
    "6d9cbf08-6d8b-4592-bb26-5e8ea1fe6b21": {
        "event_name": "ViewContent",
        "stage_name": "Discovery",
    },
    "a8d1a107-9b5a-4e40-8609-69dcd1b07b11": {
        "event_name": "InitiateCheckout",
        "stage_name": "Sales Ready",
    },
    "d04e036a-2f43-4c45-a9a2-2d484b08fb80": {
        "event_name": "AddToCart",
        "stage_name": "Needs Analysis",
    },
    "451bc1a1-7fb5-40e5-b011-d7582f1b324d": {
        "event_name": "CompleteRegistration",
        "stage_name": "Application Submitted",
    },
    "18a4112d-6085-4557-ab36-e7e8e62fd5b9": {
        "event_name": "Schedule",
        "stage_name": "Underwriting Pending",
    },
    "ebeb8e43-95d3-4629-99bf-3677bd694598": {
        "event_name": "Purchase",
        "stage_name": "Policy Issued",
        "custom_data": {"value": 1, "currency": "USD"},
    },
}


def hash_data(value):
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _first_present(data, *keys):
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _name_parts(contact_data):
    name = _first_present(
        contact_data,
        "full_name",
        "name",
        "clientName",
        "client_name",
    )
    if not name:
        first_name = _first_present(contact_data, "first_name", "firstName")
        last_name = _first_present(contact_data, "last_name", "lastName")
        return first_name, last_name

    parts = name.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def _compact_dict(data):
    return {key: value for key, value in data.items() if value not in (None, "", [])}


def _build_user_data(contact_data):
    email = _first_present(contact_data, "email", "personal_email")
    phone = _first_present(contact_data, "phone", "phone_number", "mobile_phone")
    first_name, last_name = _name_parts(contact_data)

    user_data = {}
    if email:
        user_data["em"] = [hash_data(email)]
    if phone:
        user_data["ph"] = [hash_data(phone)]
    if first_name:
        user_data["fn"] = [hash_data(first_name)]
    if last_name:
        user_data["ln"] = [hash_data(last_name)]
    return user_data


def build_stage_event_payload(opportunity_data, contact_data, stage_id, event_time=None):
    stage_config = STAGE_EVENT_MAP.get(stage_id)
    if not stage_config:
        return None

    custom_data = dict(stage_config.get("custom_data") or {})
    custom_data.update(
        _compact_dict(
            {
                "opportunity_id": opportunity_data.get("id"),
                "opportunity_name": opportunity_data.get("name"),
                "stage_id": stage_id,
                "stage_name": stage_config.get("stage_name"),
                "source": _first_present(
                    opportunity_data,
                    "source_platform",
                    "source",
                )
                or "crm",
                "campaign": _first_present(
                    opportunity_data,
                    "utm_campaign",
                    "campaign",
                    "form_id",
                ),
            }
        )
    )

    return {
        "data": [
            {
                "event_name": stage_config["event_name"],
                "event_time": event_time or int(time.time()),
                "action_source": ACTION_SOURCE,
                "user_data": _build_user_data(contact_data),
                "custom_data": custom_data,
            }
        ]
    }


def send_stage_event(opportunity_data, contact_data, stage_id):
    stage_config = STAGE_EVENT_MAP.get(stage_id)
    if not stage_config:
        log_event("No Facebook CAPI event mapped for CRM stage", stage_id=stage_id)
        return None

    if not ACCESS_TOKEN:
        log_event(
            "Skipping Facebook CAPI stage event; FB_CAPI_ACCESS_TOKEN is not configured",
            stage_id=stage_id,
            event_name=stage_config["event_name"],
        )
        return None

    payload = build_stage_event_payload(opportunity_data, contact_data, stage_id)
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PIXEL_ID}/events"

    response = requests.post(
        url,
        params={"access_token": ACCESS_TOKEN},
        json=payload,
        timeout=5,
    )
    try:
        result = response.json()
    except ValueError:
        result = {"status_code": response.status_code, "text": response.text}

    if response.status_code >= 400:
        log_event(
            "Facebook CAPI stage event rejected",
            status_code=response.status_code,
            result=result,
            stage_id=stage_id,
            event_name=stage_config["event_name"],
        )
        return result

    log_event(
        "Facebook CAPI stage event sent",
        result=result,
        stage_id=stage_id,
        event_name=stage_config["event_name"],
    )
    return result
