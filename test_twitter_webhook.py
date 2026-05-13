"""
test_twitter_webhook.py
=======================
Local in-process test for the X/Twitter lead webhook.

What this tests:
  - TiDB connection works.
  - A fake X lead event can be processed and saved to CRM tables.
  - The Flask route handles CRC GET and lead POST requests.

By default this does NOT call the real X Ads API. It patches
routes.twitter_webhook._fetch_lead_from_x so the test is repeatable.

Run:
  python test_twitter_webhook.py
"""

import json
import os
import sys
from unittest import mock

from dotenv import load_dotenv

load_dotenv()

# Force signature check off for local test-client POSTs.
os.environ["X_VERIFY_SIGNATURE"] = "false"

TEST_LEAD_ID = "test_lead_001"
ROUTE_TEST_LEAD_ID = "test_lead_002"


FAKE_META = {
    "lead_id": TEST_LEAD_ID,
    "tweet_id": "tweet_999888777",
    "card_id": "card_abc123",
    "campaign_id": "camp_xyz456",
    "account_id": os.getenv("X_AD_ACCOUNT_ID", "18ce55voctq"),
    "x_username": "testuser_x",
}


MOCK_API_RESPONSE = {
    "id": TEST_LEAD_ID,
    "field_data": [
        {"name": "full_name", "values": ["Pankaj Test"]},
        {"name": "email", "values": ["pankaj.test@example.com"]},
        {"name": "phone_number", "values": ["+919876543210"]},
        {"name": "city", "values": ["Pune"]},
        {"name": "country", "values": ["India"]},
        {"name": "company", "values": ["Test Company Pvt Ltd"]},
        {"name": "job_title", "values": ["Marketing Manager"]},
        {"name": "message", "values": ["Interested in your services"]},
    ],
    "raw": {},
}


def print_header(title):
    print("\n" + "=" * 55)
    print(title)
    print("=" * 55)


def get_test_connection():
    """Use the same TiDB connection helper used by the app code."""
    from crm_sync import get_connection

    return get_connection()


def test_db_connection():
    print_header("TEST 1 - TiDB connection")
    print(f"  HOST : {os.getenv('TIDB_HOST')}")
    print(f"  USER : {os.getenv('TIDB_USER')}")
    print(f"  DB   : {os.getenv('TIDB_DATABASE')}")
    print("  PORT : 4000")

    try:
        conn = get_test_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        print("  PASS - TiDB connection successful")
        return True
    except Exception as exc:
        print(f"  FAIL - {exc}")
        print("  HINT - This is a TiDB authentication/config issue, not a Twitter webhook issue.")
        print("         Check TIDB_USER, TIDB_PASSWORD, TIDB_DATABASE, and TiDB Cloud IP access list.")
        return False


def test_full_pipeline():
    print_header("TEST 2 - Full save pipeline with mocked X API")

    try:
        from routes.twitter_webhook import _process_twitter_lead

        with mock.patch(
            "routes.twitter_webhook._fetch_lead_from_x",
            return_value=MOCK_API_RESPONSE,
        ) as mocked_fetch:
            result = _process_twitter_lead(FAKE_META)

        mocked_fetch.assert_called_once_with(TEST_LEAD_ID, FAKE_META["account_id"])
        assert result["lead_id"] == TEST_LEAD_ID

        print("  PASS - Pipeline ran without calling the real X Ads API")
        return True
    except Exception as exc:
        print(f"  FAIL - {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_database_rows():
    print_header("TEST 3 - Verify rows saved in TiDB")

    checks = [
        (
            "crm_Contacts",
            (
                "SELECT id, first_name, last_name, email, mobile_phone, social_twitter "
                "FROM crm_Contacts WHERE id = %s"
            ),
            (f"tw-contact-{TEST_LEAD_ID}",),
        ),
        (
            "crm_Opportunities",
            (
                "SELECT id, name, source, ad_id, form_id, email, phone "
                "FROM crm_Opportunities WHERE id = %s"
            ),
            (f"tw-opportunity-{TEST_LEAD_ID}",),
        ),
        (
            "crm_Leads",
            (
                "SELECT id, firstName, lastName, email, phone, source_platform, twitter, description "
                "FROM crm_Leads "
                "WHERE source_platform = 'twitter' AND description = %s "
                "ORDER BY message_date DESC LIMIT 1"
            ),
            (f"Twitter/X lead {TEST_LEAD_ID}",),
        ),
        (
            "ContactsToOpportunities",
            (
                "SELECT contact_id, opportunity_id FROM ContactsToOpportunities "
                "WHERE contact_id = %s AND opportunity_id = %s"
            ),
            (f"tw-contact-{TEST_LEAD_ID}", f"tw-opportunity-{TEST_LEAD_ID}"),
        ),
    ]

    all_pass = True

    try:
        conn = get_test_connection()
        cursor = conn.cursor(dictionary=True)

        for table, query, params in checks:
            print(f"\n-- {table} --")
            try:
                cursor.execute(query, params)
                row = cursor.fetchone()
                if row:
                    for key, value in row.items():
                        print(f"   {key}: {value}")
                    print("   PASS - Row found")
                else:
                    print("   FAIL - Row not found")
                    all_pass = False
            except Exception as exc:
                print(f"   FAIL - Query error: {exc}")
                all_pass = False

        cursor.close()
        conn.close()
    except Exception as exc:
        print(f"  FAIL - DB connection failed: {exc}")
        return False

    return all_pass


def test_flask_route():
    print_header("TEST 4 - Flask route via test client")

    try:
        from app import app

        with mock.patch(
            "routes.twitter_webhook._process_twitter_lead",
            side_effect=lambda meta: meta,
        ) as mocked_process:
            client = app.test_client()

            resp_get = client.get("/api/twitter/webhook?crc_token=test_crc_123")
            get_body = resp_get.get_json()
            print(f"  CRC GET status : {resp_get.status_code}")
            print(f"  CRC GET body   : {get_body}")
            assert resp_get.status_code == 200, "CRC challenge failed"
            assert get_body and "response_token" in get_body, "No response_token"
            print("  PASS - CRC challenge passed")

            payload = {
                "lead_generation_card_events": [
                    {
                        "lead_id": ROUTE_TEST_LEAD_ID,
                        "tweet_id": "tweet_002",
                        "card_id": "card_002",
                        "campaign_id": "camp_002",
                        "account_id": os.getenv("X_AD_ACCOUNT_ID", "18ce55voctq"),
                        "username": "testuser_x",
                    }
                ]
            }
            resp_post = client.post(
                "/api/twitter/webhook",
                json=payload,
                content_type="application/json",
            )
            post_body = resp_post.get_json()
            print(f"\n  POST status : {resp_post.status_code}")
            print(f"  POST body   : {json.dumps(post_body, indent=2)}")

            mocked_process.assert_called_once()
            processed_meta = mocked_process.call_args.args[0]
            assert processed_meta["lead_id"] == ROUTE_TEST_LEAD_ID
            assert processed_meta["account_id"] == os.getenv("X_AD_ACCOUNT_ID", "18ce55voctq")

            if resp_post.status_code == 200 and post_body and post_body.get("success"):
                print("  PASS - Lead POST passed")
                return True

            print("  FAIL - Lead POST failed")
            return False
    except Exception as exc:
        print(f"  FAIL - {exc}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\nTwitter/X Webhook - Local Test Suite")
    print("  No Flask server needed. Runs fully in-process.")
    print("-" * 55)

    r1 = test_db_connection()
    r2 = test_full_pipeline() if r1 else (print("\nSKIP - Pipeline because DB failed") or False)
    r3 = test_database_rows() if r2 else (print("\nSKIP - DB checks because pipeline failed") or False)
    r4 = test_flask_route()

    print("\n" + "=" * 55)
    print("SUMMARY")
    print("=" * 55)
    for name, result in [
        ("TiDB Connection", r1),
        ("Full pipeline mocked", r2),
        ("Rows saved in TiDB", r3),
        ("Flask route test", r4),
    ]:
        print(f"  {'PASS' if result else 'FAIL'} - {name}")

    all_ok = all([r1, r2, r3, r4])
    print()
    if all_ok:
        print("All tests passed. Safe to deploy.")
    elif r4 and not r1:
        print("Webhook route passed, but DB-backed save tests could not run because TiDB login failed.")
    else:
        print("Some tests failed. Check output above.")
    sys.exit(0 if all_ok else 1)
