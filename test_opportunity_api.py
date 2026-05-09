import argparse
import json

import requests


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send a sample opportunity payload to the local API."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5000/api/opportunities",
        help="Opportunity API URL to test.",
    )
    return parser.parse_args()


def build_payload():
    return {
        "name": "Website Redesign Project",
        "description": "Opportunity sent from frontend test script",
        "budget": 25000,
        "expected_revenue": 25000,
        "status": "ACTIVE",
        "next_step": "Schedule intro call",
    }


def main():
    args = parse_args()
    payload = build_payload()

    print(f"POST {args.url}")
    print("Request payload:")
    print(json.dumps(payload, indent=2))

    response = requests.post(args.url, json=payload, timeout=30)
    print(f"Status: {response.status_code}")
    print("Response body:")
    print(response.text)


if __name__ == "__main__":
    main()
