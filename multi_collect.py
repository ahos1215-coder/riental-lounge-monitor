# multi_collect.py
# 38店舗ぶんの店内人数をスクレイピングして
# GAS(doPost) と Supabase(logs) に投げるスクリプト

import os
import time
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ---------- 環境変数 ----------

# GAS (Google Apps Script)
GAS_URL = os.environ.get("GAS_URL") or os.environ.get("GAS_WEBHOOK_URL")
HAS_GAS = bool(GAS_URL)
ENABLE_GAS = os.environ.get("ENABLE_GAS", "0") == "1"

# ---------- Supabase（環境変数の揺れ吸収版） ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
)
HAS_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

print(
    f"[supabase][debug] HAS_SUPABASE={HAS_SUPABASE} "
    f"url_set={bool(SUPABASE_URL)} key_set={bool(SUPABASE_SERVICE_ROLE_KEY)}"
)

SUPABASE_BRAND = "oriental"

BETWEEN_STORES_SEC = float(os.environ.get("BETWEEN_STORES_SEC", "1.0"))
GAS_MAX_RETRY = int(os.environ.get("GAS_MAX_RETRY", "3"))

# ---------- 全38店舗 ----------
STORES = [
    {"store": "長崎", "store_id": "ol_nagasaki", "url": "https://oriental-lounge.com/stores/38"},
    {"store": "福岡", "store_id": "ol_fukuoka", "url": "https://oriental-lounge.com/stores/15"},
    {"store": "小倉", "store_id": "ol_kokura", "url": "https://oriental-lounge.com/stores/16"},
    {"store": "大分", "store_id": "ol_oita", "url": "https://oriental-lounge.com/stores/40"},
    {"store": "熊本", "store_id": "ol_kumamoto", "url": "https://oriental-lounge.com/stores/22"},
    {"store": "宮崎", "store_id": "ol_miyazaki", "url": "https://oriental-lounge.com/stores/18"},
    {"store": "鹿児島", "store_id": "ol_kagoshima", "url": "https://oriental-lounge.com/stores/19"},
    {"store": "ag沖縄", "store_id": "ol_okinawa_ag", "url": "https://oriental-lounge.com/stores/20"},
    {"store": "ソウル カンナム", "store_id": "ol_gangnam", "url": "https://oriental-lounge.com/stores/34"},
    {"store": "ag札幌", "store_id": "ol_sapporo_ag", "url": "https://oriental-lounge.com/stores/1"},
    {"store": "ag仙台", "store_id": "ol_sendai_ag", "url": "https://oriental-lounge.com/stores/2"},
    {"store": "渋谷本店", "store_id": "ol_shibuya", "url": "https://oriental-lounge.com/stores/4"},
    {"store": "恵比寿", "store_id": "ol_ebisu", "url": "https://oriental-lounge.com/stores/35"},
    {"store": "ag渋谷", "store_id": "ol_shibuya_ag", "url": "https://oriental-lounge.com/stores/27"},
    {"store": "新宿", "store_id": "ol_shinjuku", "url": "https://oriental-lounge.com/stores/3"},
    {"store": "上野", "store_id": "ol_ueno", "url": "https://oriental-lounge.com/stores/33"},
    {"store": "ag上野", "store_id": "ol_ueno_ag", "url": "https://oriental-lounge.com/stores/28"},
    {"store": "柏", "store_id": "ol_kashiwa", "url": "https://oriental-lounge.com/stores/42"},
    {"store": "町田", "store_id": "ol_machida", "url": "https://oriental-lounge.com/stores/6"},
    {"store": "横浜", "store_id": "ol_yokohama", "url": "https://oriental-lounge.com/stores/23"},
    {"store": "大宮", "store_id": "ol_omiya", "url": "https://oriental-lounge.com/stores/24"},
    {"store": "宇都宮", "store_id": "ol_utsunomiya", "url": "https://oriental-lounge.com/stores/26"},
    {"store": "高崎", "store_id": "ol_takasaki", "url": "https://oriental-lounge.com/stores/37"},
    {"store": "ag名古屋", "store_id": "ol_nagoya_ag", "url": "https://oriental-lounge.com/stores/32"},
    {"store": "名古屋 錦", "store_id": "ol_nagoya_nishiki", "url": "https://oriental-lounge.com/stores/25"},
    {"store": "名古屋 栄", "store_id": "ol_nagoya_sakae", "url": "https://oriental-lounge.com/stores/8"},
    {"store": "静岡", "store_id": "ol_shizuoka", "url": "https://oriental-lounge.com/stores/7"},
    {"store": "浜松", "store_id": "ol_hamamatsu", "url": "https://oriental-lounge.com/stores/31"},
    {"store": "ag金沢", "store_id": "ol_kanazawa_ag", "url": "https://oriental-lounge.com/stores/36"},
    {"store": "大阪駅前", "store_id": "ol_osaka_ekimae", "url": "https://oriental-lounge.com/stores/41"},
    {"store": "ag梅田", "store_id": "ol_umeda_ag", "url": "https://oriental-lounge.com/stores/10"},
    {"store": "天満", "store_id": "ol_tenma", "url": "https://oriental-lounge.com/stores/39"},
    {"store": "心斎橋", "store_id": "ol_shinsaibashi", "url": "https://oriental-lounge.com/stores/11"},
    {"store": "難波", "store_id": "ol_namba", "url": "https://oriental-lounge.com/stores/12"},
    {"store": "京都", "store_id": "ol_kyoto", "url": "https://oriental-lounge.com/stores/9"},
    {"store": "神戸", "store_id": "ol_kobe", "url": "https://oriental-lounge.com/stores/13"},
    {"store": "岡山", "store_id": "ol_okayama", "url": "https://oriental-lounge.com/stores/29"},
    {"store": "ag広島", "store_id": "ol_hiroshima_ag", "url": "https://oriental-lounge.com/stores/14"},
]

# ========= GAS への POST =========

def post_to_gas(body: dict) -> None:
    if not ENABLE_GAS or not HAS_GAS:
        return

    for attempt in range(1, GAS_MAX_RETRY + 1):
        try:
            r = requests.post(GAS_URL, json=body, timeout=15)
            if r.status_code == 429 and attempt < GAS_MAX_RETRY:
                wait = 2 * attempt
                print(f"[warn] GAS 429 retry={attempt} wait={wait}s")
                time.sleep(wait)
                continue
            print(f"[GAS] store={body.get('store')} status={r.status_code} body={r.text}")
            return
        except Exception as e:
            print(f"[error] post_to_gas failed store={body.get('store')} err={e}")
            if attempt < GAS_MAX_RETRY:
                time.sleep(2 * attempt)
            return

# ========= Supabase への INSERT =========

def insert_supabase_log(store_id: str, men: int, women: int) -> None:
    if not HAS_SUPABASE:
        return

    endpoint = SUPABASE_URL.rstrip("/") + "/rest/v1/logs"
    ts = datetime.now(timezone.utc).isoformat()
    total = int(men) + int(women)

    row = {
        "store_id": store_id,
        "ts": ts,
        "men": int(men),
        "women": int(women),
        "total": total,
        "src_brand": SUPABASE_BRAND,
    }

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    try:
        r = requests.post(endpoint, json=row, headers=headers, timeout=10)
        print(f"[supabase] store_id={store_id} status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        print(f"[supabase][error] store_id={store_id} err={e}")

# ========= 新 HTML 対応のスクレイピング部 =========

def _extract_from_new_section(soup: BeautifulSoup):
    """
    新構造：
    <p class="customers-num num-male">2</p>
    <p class="customers-num num-female">9</p>
    """
    male = None
    female = None

    male_el = soup.select_one("section.branch-num-customers-wrap p.customers-num.num-male")
    female_el = soup.select_one("section.branch-num-customers-wrap p.customers-num.num-female")

    if male_el:
        m = re.search(r"\d+", male_el.get_text(strip=True))
        if m:
            male = int(m.group(0))

    if female_el:
        m = re.search(r"\d+", female_el.get_text(strip=True))
        if m:
            female = int(m.group(0))

    return male, female


def _fallback_extract(soup: BeautifulSoup):
    """
    ag 店舗など旧構造 fallback
    """
    patterns_men = [
        r"GENTLEMEN[^\d]*(\d+)",
        r"男性[^\d]*(\d+)",
    ]
    patterns_women = [
        r"LADIES[^\d]*(\d+)",
        r"女性[^\d]*(\d+)",
    ]

    txt = soup.get_text(" ", strip=True)

    men = None
    women = None

    for pat in patterns_men:
        m = re.search(pat, txt)
        if m:
            men = int(m.group(1))
            break

    for pat in patterns_women:
        m = re.search(pat, txt)
        if m:
            women = int(m.group(1))
            break

    return men, women


def scrape_store(url: str) -> tuple[int | None, int | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        )
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 新構造を最優先
    men, women = _extract_from_new_section(soup)

    # ダメなら旧構造へ fallback
    if men is None or women is None:
        fm, fw = _fallback_extract(soup)
        if men is None:
            men = fm
        if women is None:
            women = fw

    print(f"[scrape] url={url} men={men} women={women}")
    return men, women

# ========= 38店舗ぶんを一気に送る =========

def collect_all_once() -> None:
    for entry in STORES:
        store_name = entry["store"]
        store_id = entry["store_id"]
        url = entry["url"]

        try:
            men, women = scrape_store(url)
        except Exception as e:
            print(f"[error] scrape failed store={store_name} url={url} err={e}")
            continue

        if men is None or women is None:
            print(f"[warn] count missing store={store_name} men={men} women={women}")
            continue

        # GAS（任意）
        post_to_gas({"store": store_name, "men": men, "women": women})

        # Supabase
        insert_supabase_log(store_id, men, women)

        time.sleep(BETWEEN_STORES_SEC)


if __name__ == "__main__":
    collect_all_once()
