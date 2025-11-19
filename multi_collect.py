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

# GAS (Google Apps Script) 側
GAS_URL = os.environ.get("GAS_URL")
HAS_GAS = bool(GAS_URL)

# Supabase 側（Render では Environment に設定済み）
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
HAS_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

# 店舗を回す間隔（秒）
BETWEEN_STORES_SEC = float(os.environ.get("BETWEEN_STORES_SEC", "1.0"))

# GAS への POST リトライ回数
GAS_MAX_RETRY = int(os.environ.get("GAS_MAX_RETRY", "3"))

# 38店舗分の store 名（GAS の STORE_MAP と一致させる）と各店舗 URL・store_id
# store_id は Supabase の public.stores.id と一致させる
STORES = [
    # 九州・沖縄・韓国
    {"store": "長崎",       "store_id": "ol_nagasaki",      "url": "https://oriental-lounge.com/stores/38"},
    {"store": "福岡",       "store_id": "ol_fukuoka",       "url": "https://oriental-lounge.com/stores/15"},
    {"store": "小倉",       "store_id": "ol_kokura",        "url": "https://oriental-lounge.com/stores/16"},
    {"store": "大分",       "store_id": "ol_oita",          "url": "https://oriental-lounge.com/stores/40"},
    {"store": "熊本",       "store_id": "ol_kumamoto",      "url": "https://oriental-lounge.com/stores/22"},
    {"store": "宮崎",       "store_id": "ol_miyazaki",      "url": "https://oriental-lounge.com/stores/18"},
    {"store": "鹿児島",     "store_id": "ol_kagoshima",     "url": "https://oriental-lounge.com/stores/19"},
    {"store": "ag沖縄",     "store_id": "ol_okinawa_ag",    "url": "https://oriental-lounge.com/stores/20"},
    {"store": "ソウル カンナム", "store_id": "ol_gangnam", "url": "https://oriental-lounge.com/stores/34"},

    # 北海道・東北
    {"store": "ag札幌",     "store_id": "ol_sapporo_ag",    "url": "https://oriental-lounge.com/stores/1"},
    {"store": "ag仙台",     "store_id": "ol_sendai_ag",     "url": "https://oriental-lounge.com/stores/2"},

    # 関東
    {"store": "渋谷本店",   "store_id": "ol_shibuya",       "url": "https://oriental-lounge.com/stores/4"},
    {"store": "恵比寿",     "store_id": "ol_ebisu",         "url": "https://oriental-lounge.com/stores/35"},
    {"store": "ag渋谷",     "store_id": "ol_shibuya_ag",    "url": "https://oriental-lounge.com/stores/27"},
    {"store": "新宿",       "store_id": "ol_shinjuku",      "url": "https://oriental-lounge.com/stores/3"},
    {"store": "上野",       "store_id": "ol_ueno",          "url": "https://oriental-lounge.com/stores/33"},
    {"store": "ag上野",     "store_id": "ol_ueno_ag",       "url": "https://oriental-lounge.com/stores/28"},
    {"store": "柏",         "store_id": "ol_kashiwa",       "url": "https://oriental-lounge.com/stores/42"},
    {"store": "町田",       "store_id": "ol_machida",       "url": "https://oriental-lounge.com/stores/6"},
    {"store": "横浜",       "store_id": "ol_yokohama",      "url": "https://oriental-lounge.com/stores/23"},
    {"store": "大宮",       "store_id": "ol_omiya",         "url": "https://oriental-lounge.com/stores/24"},
    {"store": "宇都宮",     "store_id": "ol_utsunomiya",    "url": "https://oriental-lounge.com/stores/26"},
    {"store": "高崎",       "store_id": "ol_takasaki",      "url": "https://oriental-lounge.com/stores/37"},

    # 中部
    {"store": "ag名古屋",   "store_id": "ol_nagoya_ag",     "url": "https://oriental-lounge.com/stores/32"},
    {"store": "名古屋 錦",  "store_id": "ol_nagoya_nishiki","url": "https://oriental-lounge.com/stores/25"},
    {"store": "名古屋 栄",  "store_id": "ol_nagoya_sakae",  "url": "https://oriental-lounge.com/stores/8"},
    {"store": "静岡",       "store_id": "ol_shizuoka",      "url": "https://oriental-lounge.com/stores/7"},
    {"store": "浜松",       "store_id": "ol_hamamatsu",     "url": "https://oriental-lounge.com/stores/31"},
    {"store": "ag金沢",     "store_id": "ol_kanazawa_ag",   "url": "https://oriental-lounge.com/stores/36"},

    # 関西・中国
    {"store": "大阪駅前",   "store_id": "ol_osaka_ekimae",  "url": "https://oriental-lounge.com/stores/41"},
    {"store": "ag梅田",     "store_id": "ol_umeda_ag",      "url": "https://oriental-lounge.com/stores/10"},
    {"store": "天満",       "store_id": "ol_tenma",         "url": "https://oriental-lounge.com/stores/39"},
    {"store": "心斎橋",     "store_id": "ol_shinsaibashi",  "url": "https://oriental-lounge.com/stores/11"},
    {"store": "難波",       "store_id": "ol_namba",         "url": "https://oriental-lounge.com/stores/12"},
    {"store": "京都",       "store_id": "ol_kyoto",         "url": "https://oriental-lounge.com/stores/9"},
    {"store": "神戸",       "store_id": "ol_kobe",          "url": "https://oriental-lounge.com/stores/13"},
    {"store": "岡山",       "store_id": "ol_okayama",       "url": "https://oriental-lounge.com/stores/29"},
    {"store": "ag広島",     "store_id": "ol_hiroshima_ag",  "url": "https://oriental-lounge.com/stores/14"},
]

# ========= GAS への POST（リトライ付き） =========

def post_to_gas(body: dict) -> None:
    """
    GAS_URL に JSON POST する。429 のときは少し待ってリトライ。
    環境変数 GAS_URL が未設定なら何もしない。
    """
    if not HAS_GAS:
        return

    for attempt in range(1, GAS_MAX_RETRY + 1):
        try:
            r = requests.post(GAS_URL, json=body, timeout=15)
            if r.status_code == 429 and attempt < GAS_MAX_RETRY:
                # レート制限のときは少し待ってリトライ
                wait = 2 * attempt
                print(f"[warn] GAS 429 (rate limit) retry={attempt} wait={wait}s")
                time.sleep(wait)
                continue

            print(f"[GAS] store={body.get('store')} status={r.status_code} body={r.text}")
            return
        except Exception as e:
            print(f"[error] post_to_gas failed attempt={attempt} store={body.get('store')} err={e}")
            if attempt < GAS_MAX_RETRY:
                time.sleep(2 * attempt)
            else:
                return

# ========= Supabase への INSERT =========

def insert_supabase_log(store_id: str, men: int, women: int) -> None:
    """
    Supabase の public.logs に 1 行 INSERT する。
    DNS エラーなどで失敗しても例外は外に投げず、ログだけ出して続行する。
    """
    if not HAS_SUPABASE:
        return

    endpoint = SUPABASE_URL.rstrip("/") + "/rest/v1/logs"

    ts = datetime.now(timezone.utc).isoformat()
    row = {
        "store_id": store_id,
        "ts": ts,
        "men": int(men),
        "women": int(women),
        "total": int(men) + int(women),
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
        # ここで DNS エラーなどを握りつぶす（会社PC対策）
        print(f"[supabase][error] store_id={store_id} err={e}")

# ========= スクレイピング部 =========

def _extract_count(soup: BeautifulSoup, patterns: list[str], selectors: list[str]) -> int | None:
    text = soup.get_text(" ", strip=True)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        match = re.search(r"\d+", node.get_text(strip=True).replace(",", ""))
        if match:
            return int(match.group())
    return None


def scrape_store(url: str) -> tuple[int | None, int | None]:
    """
    店舗ページの URL を開いて men / women の人数を返す。
    取れなかったときは (None, None) を返す。
    """
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

    patterns_men = [
        r"男性\s*(\d+)\s*名",
        r"男性来店者数\s*(\d+)",
        r"男性.*?(\d+)\s*名",
    ]
    selectors_men = [
        ".store-people .male .count",
        ".store__people .male .count",
        ".male-count",
        ".js-men-count",
    ]

    patterns_women = [
        r"女性\s*(\d+)\s*名",
        r"女性来店者数\s*(\d+)",
        r"女性.*?(\d+)\s*名",
    ]
    selectors_women = [
        ".store-people .female .count",
        ".store__people .female .count",
        ".female-count",
        ".js-women-count",
    ]

    men = _extract_count(soup, patterns_men, selectors_men)
    women = _extract_count(soup, patterns_women, selectors_women)

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

        # 1) GAS へ送信（スプレッドシート用）
        body = {
            "store": store_name,  # GAS 側の STORE_MAP のキーになる（従来通り）
            "men": int(men),
            "women": int(women),
        }
        post_to_gas(body)

        # 2) Supabase へログ保存
        insert_supabase_log(store_id, int(men), int(women))

        # サイトへの負荷を下げるためにインターバルを空ける
        time.sleep(BETWEEN_STORES_SEC)


if __name__ == "__main__":
    collect_all_once()
