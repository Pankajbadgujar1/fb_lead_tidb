"""CRM opportunity stage updates with optional Facebook CAPI feedback."""

import os

from flask import Blueprint, make_response, request

from crm_sync import get_connection, log_event
from facebook_capi import STAGE_EVENT_MAP, send_stage_event


opportunity_stage_bp = Blueprint(
    "opportunity_stage",
    __name__,
    url_prefix="/api/crm",
)


def _json_response(payload, status=200):
    response = make_response(payload, status)
    response.headers["Access-Control-Allow-Origin"] = os.getenv(
        "CRM_INGEST_ALLOWED_ORIGIN",
        "*",
    )
    response.headers["Access-Control-Allow-Methods"] = "PATCH, OPTIONS"
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


def _row_to_dict(cursor, row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    columns = [column[0] for column in cursor.description or []]
    return dict(zip(columns, row))


def _table_columns(cursor, table_name):
    cursor.execute(f"SHOW COLUMNS FROM {table_name}")
    rows = cursor.fetchall()
    columns = set()
    for row in rows:
        if isinstance(row, dict):
            columns.add(row.get("Field"))
        else:
            columns.add(row[0])
    return columns


def _load_opportunity(cursor, opportunity_id):
    cursor.execute(
        "SELECT * FROM crm_Opportunities WHERE id = %s LIMIT 1",
        (opportunity_id,),
    )
    return _row_to_dict(cursor, cursor.fetchone())


def _load_contact(cursor, opportunity):
    contact_id = opportunity.get("contact")
    if not contact_id:
        cursor.execute(
            """
            SELECT contact_id
            FROM ContactsToOpportunities
            WHERE opportunity_id = %s
            LIMIT 1
            """,
            (opportunity.get("id"),),
        )
        link = _row_to_dict(cursor, cursor.fetchone())
        contact_id = link.get("contact_id") if link else None

    if not contact_id:
        return {}

    cursor.execute(
        "SELECT * FROM crm_Contacts WHERE id = %s LIMIT 1",
        (contact_id,),
    )
    return _row_to_dict(cursor, cursor.fetchone()) or {}


def _update_opportunity_stage(cursor, opportunity_id, stage_id):
    columns = _table_columns(cursor, "crm_Opportunities")
    assignments = ["sales_stage = %s"]
    values = [stage_id]

    if "updatedAt" in columns:
        assignments.append("updatedAt = CURRENT_TIMESTAMP(3)")

    cursor.execute(
        f"""
        UPDATE crm_Opportunities
        SET {", ".join(assignments)}
        WHERE id = %s
        """,
        (*values, opportunity_id),
    )


def _merged_contact_data(db_contact, request_contact):
    contact = dict(db_contact or {})
    contact.update({key: value for key, value in (request_contact or {}).items() if value})
    return contact


def _merged_opportunity_data(db_opportunity, request_opportunity, opportunity_id):
    opportunity = dict(db_opportunity or {})
    opportunity.update(
        {key: value for key, value in (request_opportunity or {}).items() if value}
    )
    opportunity["id"] = opportunity_id
    return opportunity


@opportunity_stage_bp.route("/opportunities/<opportunity_id>/stage", methods=["PATCH", "OPTIONS"])
def update_opportunity_stage(opportunity_id):
    if request.method == "OPTIONS":
        return _json_response("", 204)

    api_key_error = _require_api_key()
    if api_key_error:
        return api_key_error

    payload = request.get_json(silent=True) or {}
    stage_id = _clean(
        payload.get("stage_id")
        or payload.get("sales_stage")
        or payload.get("new_stage_id")
    )
    if not stage_id:
        return _json_response({"success": False, "error": "stage_id is required."}, 400)

    opportunity_id = _clean(opportunity_id)
    if not opportunity_id:
        return _json_response(
            {"success": False, "error": "opportunity_id is required."},
            400,
        )

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        before_update = _load_opportunity(cursor, opportunity_id)
        if not before_update:
            return _json_response(
                {"success": False, "error": "Opportunity not found."},
                404,
            )

        _update_opportunity_stage(cursor, opportunity_id, stage_id)
        after_update = _load_opportunity(cursor, opportunity_id) or before_update
        contact_data = _merged_contact_data(
            _load_contact(cursor, after_update),
            payload.get("contact") or {},
        )
        opportunity_data = _merged_opportunity_data(
            after_update,
            payload.get("opportunity") or {},
            opportunity_id,
        )
        conn.commit()

        fb_result = None
        fb_error = None
        try:
            fb_result = send_stage_event(opportunity_data, contact_data, stage_id)
        except Exception as exc:
            fb_error = str(exc)
            log_event(
                "Facebook CAPI stage event failed without blocking CRM update",
                opportunity_id=opportunity_id,
                stage_id=stage_id,
                error=fb_error,
            )

        stage_config = STAGE_EVENT_MAP.get(stage_id) or {}
        return _json_response(
            {
                "success": True,
                "opportunity_id": opportunity_id,
                "new_stage": stage_id,
                "facebook_event": stage_config.get("event_name"),
                "facebook_result": fb_result,
                "facebook_error": fb_error,
            },
            200,
        )
    except Exception as exc:
        if conn:
            conn.rollback()
        log_event(
            "Opportunity stage update failed",
            opportunity_id=opportunity_id,
            stage_id=stage_id,
            error=str(exc),
        )
        return _json_response({"success": False, "error": str(exc)}, 500)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
