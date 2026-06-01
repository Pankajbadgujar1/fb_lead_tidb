import requests
import hashlib
import time

PIXEL_ID = "960269016759356"
ACCESS_TOKEN = "EAALFZA4txkFQBRsldd4HT6aAp2aZBkZCJeF1WanSjZCayUQD1J30sJbuDHHnq1yQIdg1BPENCyQl0sIdyT4Fx3hr8dQzzB4YKrae9sVs2PZCSQQz7KvTT1I1GRf6xa0zt5zhRScLDdq7JDZAqiuhz54el8VqeL5mCHRPcLwGPNAb6TchatAmTFPXiNZARKJnwZDZD"  # paste directly for testing only

def hash_data(value):
    return hashlib.sha256(value.lower().strip().encode()).hexdigest()

# Test payload
payload = {
    "data": [{
        "event_name": "Lead",
        "event_time": int(time.time()),
        "action_source": "crm",
        "user_data": {
            "em": [hash_data("test@gmail.com")],
            "ph": [hash_data("+919826565385")],
        },
        "custom_data": {
            "stage_name": "New Lead Intake",
            "source": "facebook"
        }
    }],
    "test_event_code": "TEST12345"  # remove in production
}

url = f"https://graph.facebook.com/v18.0/{PIXEL_ID}/events"

response = requests.post(
    url,
    params={"access_token": ACCESS_TOKEN},
    json=payload
)

print("Status:", response.status_code)
print("Response:", response.json())