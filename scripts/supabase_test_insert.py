from datetime import datetime, timezone
import os
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

endpoint = f"{SUPABASE_URL}/rest/v1/logs"

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

now = datetime.now(timezone.utc)

row = {
    "store_id": "ol_nagasaki",
    "ts": now.isoformat(),

    "men": 1,
    "women": 2,
    "total": 3,

    # ★ NOT NULL のカラムをここで埋める
    "src_brand": "oriental",
    "src_store": "長崎店",
    "src_url": "https://oriental-lounge.com/stores/38",
    "src_version": "test-script",
    # weather_code / temp / precip_mm などは NULL OK なら省略でよい
}

resp = requests.post(endpoint, json=row, headers=headers, timeout=10)
print("status:", resp.status_code)
print("body:", resp.text)
