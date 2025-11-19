# scripts/supabase_test_insert.py
import os
import datetime as dt
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

endpoint = f"{SUPABASE_URL}/rest/v1/logs"

now_utc = dt.datetime.now(dt.timezone.utc)

row = {
    "store_id": "ol_nagasaki",      # テストなので長崎固定でOK
    "ts": now_utc.isoformat(),
    "men": 1,
    "women": 2,
    "total": 3,
}

headers = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

resp = requests.post(endpoint, json=row, headers=headers, timeout=10)
print("status:", resp.status_code)
print("body:", resp.text)
