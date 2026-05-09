import argparse
import json

import requests
from requests.exceptions import RequestException


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send a sample Facebook leadgen webhook payload to a local webhook URL."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5000/api/webhook",
        help="Webhook URL to test.",
    )
    parser.add_argument(
        "--lead-id",
        default="123456789012345",
        help="Lead ID to place in the webhook payload.",
    )
    return parser.parse_args()


def build_payload(lead_id):
    return {
        "object": "page",
        "entry": [
            {
                "id": "test-page-id",
                "time": 1777020903,
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {
                            "ad_id": "test-ad-001",
                            "form_id": "test-form-001",
                            "leadgen_id": lead_id,
                            "page_id": "test-page-001",
                            "created_time": 1777020903,
                        },
                    }
                ],
            }
        ],
    }


def main():
    args = parse_args()
    payload = build_payload(args.lead_id)
    print(f"POST {args.url}")
    print("Request payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(args.url, json=payload, timeout=30)
    except RequestException as exc:
        print(f"Webhook request failed: {exc}")
        print("Start one of these first, then retry:")
        print(r"  .\venv\Scripts\python.exe app.py")
        print(r"  .\venv\Scripts\python.exe webhook_debug.py -- if you are testing port 3000")
        return

    print(f"Status: {response.status_code}")
    print("Response body:")
    print(response.text)


if __name__ == "__main__":
    main()
