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

    # logs テーブルに実際に存在する NOT NULL カラムだけ送る
    "src_brand": "oriental",
    # weather 系カラムは NULL OK なら省略で OK
}

resp = requests.post(endpoint, json=row, headers=headers, timeout=10)
print("status:", resp.status_code)
print("body:", resp.text)
