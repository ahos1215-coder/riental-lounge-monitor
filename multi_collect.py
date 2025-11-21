# multi_collect.py
# 38店舗ぶんの店内人数をスクレイピングして
# GAS(doPost) と Supabase(logs) に投げるスクリプト
#
# 追加: Open-Meteo から天気を1回だけ取得して
#      全店舗のレコードに
#      weather_code / weather_label / temp_c / precip_mm を付与する

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

# ローカル .env：SUPABASE_SERVICE_KEY
# Render     ：SUPABASE_SERVICE_ROLE_KEY
SUPABASE_SERVICE_ROLE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
)

HAS_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

# デバッグ出力（問題解決したら消してOK）
print(
    f"[supabase][debug] HAS_SUPABASE={HAS_SUPABASE} "
    f"url_set={bool(SUPABASE_URL)} key_set={bool(SUPABASE_SERVICE_ROLE_KEY)}"
)

# Supabase logs.src_brand に入れるブランド名
SUPABASE_BRAND = "oriental"

# 店舗を回す間隔（秒）
BETWEEN_STORES_SEC = float(os.environ.get("BETWEEN_STORES_SEC", "0.0"))

# GAS への POST リトライ回数
GAS_MAX_RETRY = int(os.environ.get("GAS_MAX_RETRY", "3"))

# ---------- 天気 API 設定（Open-Meteo） ----------

# 有効/無効フラグ（とりあえずデフォルト ON）
ENABLE_WEATHER = os.environ.get("ENABLE_WEATHER", "1") == "1"

# 基準地点（とりあえず長崎市近辺）
WEATHER_LAT = float(os.environ.get("WEATHER_LAT", "32.75"))
WEATHER_LON = float(os.environ.get("WEATHER_LON", "129.87"))

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

# ========= 天気ユーティリティ =========

def _weather_code_to_label(code: int | None) -> str | None:
    """Open-Meteo weathercode をざっくり日本語ラベルに変換"""
    if code is None:
        return None
    if code == 0:
        return "快晴"
    if code in (1, 2, 3):
        return "晴れ／一部曇り"
    if code in (45, 48):
        return "霧"
    if 51 <= code <= 67:
        return "雨（霧雨〜強い雨）"
    if 71 <= code <= 77:
        return "雪"
    if 80 <= code <= 82:
        return "にわか雨"
    if 95 <= code <= 99:
        return "雷雨"
    return f"その他({code})"


def fetch_current_weather() -> tuple[int | None, str | None, float | None, float | None]:
    """
    Open-Meteo から現在の
      - weather_code
      - temperature_2m (気温, ℃)
      - precipitation (直近1時間の降水量, mm)
    を1回だけ取得。失敗したら (None, None, None, None) を返す。
    """
    if not ENABLE_WEATHER:
        return None, None, None, None

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": WEATHER_LAT,
        "longitude": WEATHER_LON,
        "current": "weather_code,temperature_2m,precipitation",
        "timezone": "Asia/Tokyo",
    }

    try:
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})

        code = current.get("weather_code")
        temp_c = current.get("temperature_2m")
        precip_mm = current.get("precipitation")

        label = _weather_code_to_label(code) if isinstance(code, int) else None

        print(
            f"[weather] code={code} label={label} "
            f"temp_c={temp_c} precip_mm={precip_mm}"
        )
        return code, label, temp_c, precip_mm
    except Exception as e:
        print(f"[weather][error] failed to fetch weather: {e}")
        return None, None, None, None

# ========= GAS への POST =========

def post_to_gas(body: dict) -> None:
    if not ENABLE_GAS:
        return
    if not HAS_GAS:
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
            else:
                return

# ========= Supabase への INSERT =========

def insert_supabase_log(
    store_id: str,
    men: int,
    women: int,
    weather_code: int | None,
    weather_label: str | None,
    temp_c: float | None,
    precip_mm: float | None,
) -> None:
    if not HAS_SUPABASE:
        return

    endpoint = SUPABASE_URL.rstrip("/") + "/rest/v1/logs"
    ts = datetime.now(timezone.utc).isoformat()
    total = int(men) + int(women)

    row: dict[str, object] = {
        "store_id": store_id,
        "ts": ts,
        "men": int(men),
        "women": int(women),
        "total": total,
        "src_brand": SUPABASE_BRAND,
    }

    # logs テーブルに weather / 気温 / 降水量 カラムがある前提
    if weather_code is not None:
        row["weather_code"] = weather_code
    if weather_label is not None:
        row["weather_label"] = weather_label
    if temp_c is not None:
        row["temp_c"] = float(temp_c)
    if precip_mm is not None:
        row["precip_mm"] = float(precip_mm)

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    try:
        r = requests.post(endpoint, json=row, headers=headers, timeout=10)
        print(
            f"[supabase] store_id={store_id} status={r.status_code} "
            f"body={r.text[:200]}"
        )
    except Exception as e:
        print(f"[supabase][error] store_id={store_id} err={e}")

# ========= スクレイピング部 =========

def _extract_count(
    soup: BeautifulSoup,
    patterns: list[str],
    selectors: list[str],
) -> int | None:
    """旧HTML向けのフォールバック用."""
    text = soup.get_text(" ", strip=True)

    # テキストパターン
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    # CSS セレクタ
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        match = re.search(r"\d+", node.get_text(strip=True).replace(",", ""))
        if match:
            return int(match.group())
    return None


def scrape_store(url: str) -> tuple[int | None, int | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        )
    }

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. 新デザイン（現在の来客者数セクション）を最優先で読む
    men_node = soup.select_one(
        "section[aria-label='現在の来客者数'] .customers-num.num-male"
    )
    women_node = soup.select_one(
        "section[aria-label='現在の来客者数'] .customers-num.num-female"
    )

    if men_node and women_node:
        try:
            men = int(re.search(r"\d+", men_node.get_text(strip=True)).group())
            women = int(re.search(r"\d+", women_node.get_text(strip=True)).group())
            print(f"[scrape] (new) url={url} men={men} women={women}")
            return men, women
        except Exception:
            # 何かおかしくても下のフォールバックに回す
            pass

    # 2. 旧デザイン or 予備パターン（今後の変更に備えて残しておく）
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

    print(f"[scrape] (fallback) url={url} men={men} women={women}")
    return men, women

# ========= 38店舗ぶんを一気に送る =========

def collect_all_once() -> None:
    print("collect_all_once.start")

    # 天気は 1 回だけ取得して全店舗に使い回す
    weather_code: int | None = None
    weather_label: str | None = None
    temp_c: float | None = None
    precip_mm: float | None = None
    if ENABLE_WEATHER:
        weather_code, weather_label, temp_c, precip_mm = fetch_current_weather()

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

        # GAS（任意） — 仕様を壊さないよう、今は天気コードだけ送る
        body = {
            "store": store_name,
            "men": int(men),
            "women": int(women),
        }
        if weather_code is not None:
            body["weather_code"] = weather_code
        if weather_label is not None:
            body["weather_label"] = weather_label

        post_to_gas(body)

        # Supabase
        insert_supabase_log(
            store_id,
            int(men),
            int(women),
            weather_code,
            weather_label,
            temp_c,
            precip_mm,
        )

        time.sleep(BETWEEN_STORES_SEC)


if __name__ == "__main__":
    collect_all_once()
