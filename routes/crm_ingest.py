"""CRM contact ingestion route.

This module defines a Flask Blueprint that exposes a single REST endpoint
`POST /api/crm/contacts/ingest` to ingest lead/contact data from supported
platforms (facebook, instagram) and insert a mapped record into the
`crm_Leads` table in TiDB (MySQL-compatible).
"""

import json
import os
import uuid
from datetime import datetime, date

try:
    import pymysql  # Preferred for Vercel runtime (requirements.txt)
except Exception:  # pragma: no cover
    pymysql = None

try:
    import mysql.connector as mysql_connector  # Available in some local environments
except Exception:  # pragma: no cover
    mysql_connector = None
from flask import Blueprint, request


crm_ingest_bp = Blueprint("crm_ingest", __name__, url_prefix="/api/crm")

TABLE_NAME = "crm_Leads"


def _get_db_connection():
    # DB connection:
    # - On Vercel this repo uses PyMySQL (api/index.py + requirements.txt)
    # - Locally you may have mysql.connector available
    host = os.environ.get("TIDB_HOST")
    port = int(os.environ.get("TIDB_PORT", 4000))
    user = os.environ.get("TIDB_USER")
    password = os.environ.get("TIDB_PASSWORD")
    database = os.environ.get("TIDB_DB") or os.environ.get("TIDB_DATABASE")

    if pymysql is not None:
        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            ssl={"verify_cert": True, "verify_identity": True},
            connect_timeout=10,
            read_timeout=10,
            write_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )

    if mysql_connector is not None:
        return mysql_connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            ssl_disabled=False,
        )

    raise RuntimeError("No supported MySQL client available (pymysql or mysql-connector-python).")


def _truncate(value, max_length=191):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:max_length]


def _split_name(full_name):
    full_name = (full_name or "").strip()
    if not full_name:
        return None, "Unknown"

    parts = full_name.split()
    first_name = parts[0] if parts else None
    last_name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
    if not last_name:
        last_name = "Unknown"
    return _truncate(first_name), _truncate(last_name)


def _parse_address_parts(address):
    address = (address or "").strip()
    if not address:
        return None, None, None

    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return _truncate(parts[0]), None, None
    if len(parts) == 2:
        return _truncate(parts[0]), _truncate(parts[1]), None

    city = parts[0]
    country = parts[-1]
    state = ", ".join(parts[1:-1])
    return _truncate(city), _truncate(state), _truncate(country)


def _parse_date_yyyy_mm_dd(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        # Expected format: YYYY-MM-DD
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime_mysql(value):
    value = (value or "").strip()
    if not value:
        return None
    # Accept both "YYYY-MM-DD HH:MM:SS" and ISO 8601.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


@crm_ingest_bp.route("/contacts/ingest", methods=["POST"])
def ingest_contact():
    # validation: parse and validate request body
    payload = request.get_json(silent=True) or {}
    source_platform_raw = payload.get("source_platform")
    source_platform = (source_platform_raw or "").strip().lower() or None
    if source_platform is not None and source_platform not in {"facebook", "instagram", "linkedin", "twitter"}:
        return {
            "success": False,
            "error": "source_platform must be 'facebook', 'instagram', 'linkedin', or 'twitter' when provided.",
        }, 400

    name = (payload.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required."}, 400

    email = _truncate(payload.get("email"))
    if email and "@" not in email:
        return {"success": False, "error": "email must contain '@' if provided."}, 400

    first_name, last_name = _split_name(name)
    if not last_name:
        last_name = "Unknown"

    # mapping: common fields
    contact_id = str(uuid.uuid4())
    now_utc = datetime.utcnow()
    mobile_phone = _truncate(payload.get("phone"))

    # mapping: platform-specific fields
    company = None
    job_title = None
    description = None
    website = None
    twitter = None
    linkedin_url = None
    birthday = None  # date
    address = None
    city = None
    state = None
    country = None
    headline = None
    username = None
    message_snippet = None
    message_date = None

    if source_platform in {"facebook", "linkedin", "twitter"}:
        headline = _truncate(payload.get("headline"), 255)
        job_title = _truncate(payload.get("headline"))
        company = _truncate(payload.get("current_company"))
        description = _truncate(payload.get("about"))
        website = _truncate(payload.get("website"), 255)
        twitter = _truncate(payload.get("twitter"), 255)
        linkedin_url = _truncate(payload.get("linkedin_url"), 255)
        birthday = _parse_date_yyyy_mm_dd(payload.get("birthday"))
        address = _truncate(payload.get("address"))
        city, state, country = _parse_address_parts(address)
    elif source_platform == "instagram":
        username = _truncate(payload.get("username"))
        message_snippet = payload.get("message_snippet")
        message_date = _parse_datetime_mysql(payload.get("message_date"))
        description = _truncate(message_snippet)
    else:
        # source_platform not provided: map best-effort from whichever fields exist.
        headline = _truncate(payload.get("headline"), 255)
        job_title = _truncate(payload.get("headline"))
        company = _truncate(payload.get("current_company"))
        about_text = payload.get("about")
        message_snippet = payload.get("message_snippet")
        description = _truncate(message_snippet) or _truncate(about_text)
        website = _truncate(payload.get("website"), 255)
        twitter = _truncate(payload.get("twitter"), 255)
        linkedin_url = _truncate(payload.get("linkedin_url"), 255)
        birthday = _parse_date_yyyy_mm_dd(payload.get("birthday"))
        username = _truncate(payload.get("username"))
        message_date = _parse_datetime_mysql(payload.get("message_date"))
        address = _truncate(payload.get("address"))
        city, state, country = _parse_address_parts(address)

    # insert: duplicate detection by email + source_platform (when email present)
    conn = None
    try:
        conn = _get_db_connection()
        # insert: open a dict cursor for either driver
        if pymysql is not None and conn.__class__.__module__.startswith("pymysql"):
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True)
        try:
            if email:
                try:
                    if source_platform:
                        cursor.execute(
                            f"SELECT id FROM {TABLE_NAME} WHERE email=%s AND source_platform=%s LIMIT 1",
                            (email, source_platform),
                        )
                    else:
                        cursor.execute(
                            f"SELECT id FROM {TABLE_NAME} WHERE email=%s LIMIT 1",
                            (email,),
                        )
                    existing = cursor.fetchone()
                except Exception:
                    # If the target table doesn't have source_platform in this environment,
                    # fall back to a simpler duplicate check by email only.
                    cursor.execute(
                        f"SELECT id FROM {TABLE_NAME} WHERE email=%s LIMIT 1",
                        (email,),
                    )
                    existing = cursor.fetchone()

                if existing and existing.get("id"):
                    return {
                        "success": False,
                        "error": f"Contact with this email already exists for source_platform '{source_platform}'.",
                    }, 409

            # insert: parameterized query into crm_Leads (matches provided schema)
            cursor.execute(
                f"""
                INSERT INTO {TABLE_NAME}
                (
                    id,
                    firstName,
                    lastName,
                    company,
                    jobTitle,
                    email,
                    phone,
                    description,
                    createdAt,
                    source_platform,
                    headline,
                    website,
                    twitter,
                    linkedin_url,
                    birthday,
                    username,
                    message_snippet,
                    message_date,
                    address,
                    city,
                    state,
                    country
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    contact_id,
                    first_name or "Unknown",
                    last_name,
                    company,
                    job_title,
                    email,
                    mobile_phone,
                    description,
                    now_utc,
                    source_platform,
                    headline,
                    website,
                    twitter,
                    linkedin_url,
                    birthday,
                    username,
                    message_snippet,
                    message_date,
                    address,
                    city,
                    state,
                    country,
                ),
            )
            conn.commit()
        finally:
            try:
                cursor.close()
            except Exception:
                pass

        # response: success payload
        return {
            "success": True,
            "message": "Contact created successfully",
            "contact_id": contact_id,
            "source_platform": source_platform,
        }, 201
    except Exception as exc:
        # response: DB error
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        return {"success": False, "error": str(exc)}, 500
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
