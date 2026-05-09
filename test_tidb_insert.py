import argparse
import json
from datetime import datetime, timezone

from crm_sync import get_connection, log_event, save_lead_to_tidb


def build_sample_lead(lead_id):
    return {
        "id": lead_id,
        "created_time": datetime.now(timezone.utc).isoformat(),
        "field_data": [
            {"name": "full_name", "values": ["Test User"]},
            {"name": "email", "values": [f"{lead_id}@example.com"]},
            {"name": "phone_number", "values": ["9876543210"]},
            {"name": "company_name", "values": ["Signimus Technologies"]},
            {"name": "budget", "values": ["15000"]},
            {
                "name": "message",
                "values": ["Inserted from test_tidb_insert.py"],
            },
        ],
    }


def build_meta(lead_id):
    return {
        "lead_id": lead_id,
        "form_id": "test-form-001",
        "page_id": "test-page-001",
        "ad_id": "test-ad-001",
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Insert a sample Facebook lead into TiDB."
    )
    parser.add_argument(
        "--lead-id",
        default=f"manual-test-{int(datetime.now().timestamp())}",
        help="Lead ID to use for the sample insert.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only check whether the given lead ID already exists in TiDB.",
    )
    return parser.parse_args()


def fetch_saved_records(lead_id):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT lead_id, form_id, page_id, ad_id, full_name, email, phone, created_at
            FROM facebook_leads
            WHERE lead_id = %s
            """,
            (lead_id,),
        )
        facebook_lead = cursor.fetchone()

        cursor.execute(
            """
            SELECT id, account, assigned_to, email, first_name, last_name, mobile_phone,
                   contact_type_id, accountsIDs, created_on
            FROM crm_Contacts
            WHERE id = %s
            """,
            (f"fb-contact-{lead_id}",),
        )
        contact = cursor.fetchone()

        cursor.execute(
            """
            SELECT id, account, assigned_to, budget, campaign, contact, currency,
                   expected_revenue, name, sales_stage, type, status, created_on
            FROM crm_Opportunities
            WHERE id = %s
            """,
            (f"fb-opportunity-{lead_id}",),
        )
        opportunity = cursor.fetchone()

        return {
            "facebook_lead": facebook_lead,
            "contact": contact,
            "opportunity": opportunity,
        }
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def main():
    args = parse_args()
    print(f"Using lead ID: {args.lead_id}", flush=True)

    try:
        if not args.verify_only:
            lead_data = build_sample_lead(args.lead_id)
            meta = build_meta(args.lead_id)
            log_event("Starting manual TiDB insert test", meta=meta)
            save_lead_to_tidb(lead_data, meta)
            print("Insert completed successfully.", flush=True)
            print(json.dumps({"meta": meta, "lead_data": lead_data}, indent=2), flush=True)

        saved_records = fetch_saved_records(args.lead_id)
        if any(saved_records.values()):
            print("Lead flow found in TiDB:", flush=True)
            print(json.dumps(saved_records, indent=2, default=str), flush=True)
        else:
            print("Lead not found in TiDB.", flush=True)
    except Exception as exc:
        print(f"TiDB test failed: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
