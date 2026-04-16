# multi_collect.py
# 38店舗ぶんの店内人数をスクレイピングして
# GAS(doPost) と Supabase(logs) に投げるスクリプト
#
# 追加: Open-Meteo から天気を1回だけ取得して
#      全店舗のレコードに
#      weather_code / weather_label / temp_c / precip_mm を付与する

import json
import os
import re
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Flask と同じリポジトリルートの .env / .env.local を読む（単体実行時も HAS_SUPABASE が揃う）
_root = Path(__file__).resolve().parent
if (_root / ".env").is_file():
    load_dotenv(_root / ".env", override=False)
if (_root / ".env.local").is_file():
    load_dotenv(_root / ".env.local", override=True)

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

# ---------- 相席屋 (aiseki-ya.com) ----------
# SSR でパーセンテージが初期 HTML に埋め込まれている。
# 実人数は公開されていないため、座席数 × % で逆算する。
AISEKIYA_BRAND = "aisekiya"
AISEKIYA_TOP_URL = "https://aiseki-ya.com/"

AISEKIYA_STORES: dict[str, dict] = {
    "shibuya2":              {"name": "渋谷店",     "store_id": "ay_shibuya",     "pref": "tokyo",     "tables": 16, "vip": 3},
    "ikebukurohigashiguchi": {"name": "池袋東口店", "store_id": "ay_ikebukuro",   "pref": "tokyo",     "tables": 11, "vip": 3},
    "ueno":                  {"name": "上野店",     "store_id": "ay_ueno",        "pref": "tokyo",     "tables": 14, "vip": 1},
    "chibachuo":             {"name": "千葉中央店", "store_id": "ay_chiba",       "pref": "chiba",     "tables": 19, "vip": 3},
    "yokonishi":             {"name": "横浜西口店", "store_id": "ay_yokohama",    "pref": "kanagawa",  "tables": 10, "vip": 7},
    "nigatabandai":          {"name": "新潟万代店", "store_id": "ay_niigata",     "pref": "niigata",   "tables": 13, "vip": 2},
}

# 男女別の最大収容枠 = (テーブル数 + VIP数) × 2名
def _aisekiya_capacity(slug: str) -> int:
    info = AISEKIYA_STORES.get(slug)
    if not info:
        return 0
    return (info["tables"] + info["vip"]) * 2

# 店舗を回す間隔（秒）— 書き込みフェーズで使用
BETWEEN_STORES_SEC = float(os.environ.get("BETWEEN_STORES_SEC", "0.0"))

# 並列スクレイピングのワーカー数（デフォルト10）
SCRAPE_MAX_WORKERS = int(os.environ.get("SCRAPE_MAX_WORKERS", "10"))

# GAS への POST リトライ回数
GAS_MAX_RETRY = int(os.environ.get("GAS_MAX_RETRY", "3"))

# ---------- 天気 API 設定（Open-Meteo） ----------

# 有効/無効フラグ（とりあえずデフォルト ON）
ENABLE_WEATHER = os.environ.get("ENABLE_WEATHER", "1") == "1"

# Open-Meteo は短時間に多数リクエストすると 429 になる。同一座標はディスクキャッシュで再取得しない。
# 既定 1 時間（5 分おきの収集でも実質 1 回/時間/エリア）
WEATHER_CACHE_TTL_SEC = int(os.environ.get("WEATHER_CACHE_TTL_SEC", "7200"))
# 実 HTTP の最小間隔（秒）。バースト緩和
WEATHER_HTTP_MIN_INTERVAL_SEC = float(os.environ.get("WEATHER_HTTP_MIN_INTERVAL_SEC", "6.0"))
# 接続エラー等の再試行（429 とは別）
WEATHER_HTTP_MAX_RETRIES = int(os.environ.get("WEATHER_HTTP_MAX_RETRIES", "3"))
# 429: 長時間 sleep すると Gunicorn の worker timeout（既定30s）で落ちるため、短い待機＋最大1回だけ再試行
WEATHER_429_RETRY_SLEEP_SEC = float(os.environ.get("WEATHER_429_RETRY_SLEEP_SEC", "5.0"))
WEATHER_429_EXTRA_TRIES = int(os.environ.get("WEATHER_429_EXTRA_TRIES", "1"))
WEATHER_FETCH_WINDOW_MINUTES = int(os.environ.get("WEATHER_FETCH_WINDOW_MINUTES", "10"))
_CACHE_DIR = _root / ".cache"
_DEFAULT_WEATHER_CACHE_PATH = _CACHE_DIR / "open_meteo_weather_cache.json"
WEATHER_CACHE_PATH = Path(os.environ.get("WEATHER_CACHE_PATH", str(_DEFAULT_WEATHER_CACHE_PATH)))

# 同一プロセス内の連続 Open-Meteo 呼び出しの間隔制御
_last_open_meteo_http_at: float = 0.0

# ---------- 失敗アラート設定 ----------
# Webhook URL（LINE Notify / Slack / Discord 等）。未設定時はアラート無効。
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
# 収集失敗率がこの値以上になったらアラートを送る（0.5 = 50%以上失敗）
ALERT_FAIL_RATIO_THRESHOLD = float(os.environ.get("ALERT_FAIL_RATIO_THRESHOLD", "0.5"))

# ---------- LINE Push（DOM 構造変更アラート用） ----------
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_USER_ID = os.environ.get("LINE_USER_ID", "").strip()

# DOM アラートのクールダウン（秒）。デフォルト 6 時間
DOM_ALERT_COOLDOWN_SEC = int(os.environ.get("DOM_ALERT_COOLDOWN_SEC", str(6 * 3600)))
_DOM_ALERT_FLAG_PATH = _root / "data" / "dom_alert_sent.txt"

# 基準地点（とりあえず長崎市近辺）
WEATHER_LAT = float(os.environ.get("WEATHER_LAT", "32.75"))
WEATHER_LON = float(os.environ.get("WEATHER_LON", "129.87"))

# 都道府県ごとの代表座標（無ければ環境変数にフォールバック）
PREF_COORDS: dict[str, tuple[float, float]] = {
    "nagasaki": (32.744, 129.873),
    "fukuoka": (33.5902, 130.4017),
    "oita": (33.2396, 131.6093),
    "kumamoto": (32.7898, 130.7417),
    "miyazaki": (31.9077, 131.4202),
    "kagoshima": (31.5966, 130.5571),
    "okinawa": (26.2124, 127.6809),
    "hokkaido": (43.0621, 141.3544),
    "miyagi": (38.2688, 140.8721),
    "tokyo": (35.6895, 139.6917),
    "kanagawa": (35.4437, 139.6380),
    "saitama": (35.8617, 139.6455),
    "chiba": (35.6073, 140.1063),
    "tochigi": (36.5552, 139.8828),
    "gunma": (36.3907, 139.0604),
    "aichi": (35.1815, 136.9066),
    "shizuoka": (34.9756, 138.3828),
    "ishikawa": (36.5947, 136.6256),
    "osaka": (34.6937, 135.5023),
    "kyoto": (35.0116, 135.7681),
    "hyogo": (34.6901, 135.1955),
    "okayama": (34.6551, 133.9195),
    "hiroshima": (34.3853, 132.4553),
    "niigata": (37.9161, 139.0364),
    "seoul": (37.5665, 126.9780),
}

# ---------- 全38店舗 (frontend/src/data/stores.json が単一ソース) ----------

_STORES_JSON_PATH = _root / "frontend" / "src" / "data" / "stores.json"
with _STORES_JSON_PATH.open(encoding="utf-8") as _f:
    STORES: list[dict] = json.load(_f)


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


def _weather_location_key(lat: float, lon: float) -> str:
    return f"{round(lat, 4)},{round(lon, 4)}"


def _load_weather_disk_cache() -> dict[str, dict]:
    try:
        if WEATHER_CACHE_PATH.is_file():
            with WEATHER_CACHE_PATH.open(encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception as e:
        print(f"[weather][cache] load failed: {e}")
    return {}


def _save_weather_disk_cache(cache: dict[str, dict]) -> None:
    try:
        WEATHER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        # 古いエントリを削除（ファイル肥大化防止。7日より古いものは破棄）
        max_age = 7 * 24 * 3600
        pruned: dict[str, dict] = {}
        for k, v in cache.items():
            ts = float(v.get("ts", 0))
            if now - ts <= max_age:
                pruned[k] = v
        tmp = WEATHER_CACHE_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False, indent=0)
        tmp.replace(WEATHER_CACHE_PATH)
    except Exception as e:
        print(f"[weather][cache] save failed: {e}")


def _enforce_open_meteo_spacing() -> None:
    """同一プロセス内で Open-Meteo へのリクエストを短時間に連打しない。"""
    global _last_open_meteo_http_at
    if WEATHER_HTTP_MIN_INTERVAL_SEC <= 0:
        return
    gap = time.time() - _last_open_meteo_http_at
    if gap < WEATHER_HTTP_MIN_INTERVAL_SEC:
        time.sleep(WEATHER_HTTP_MIN_INTERVAL_SEC - gap)


def _tuple_from_cache_entry(entry: dict) -> tuple[int | None, str | None, float | None, float | None]:
    code = entry.get("code")
    label = entry.get("label")
    temp_c = entry.get("temp_c")
    precip_mm = entry.get("precip_mm")
    if code is not None and not isinstance(code, int):
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None
    return code, label if isinstance(label, str) else None, temp_c, precip_mm


def fetch_current_weather(
    lat: float | None = None, lon: float | None = None
) -> tuple[int | None, str | None, float | None, float | None]:
    """
    Open-Meteo から現在の
      - weather_code
      - temperature_2m (気温, ℃)
      - precipitation (直近1時間の降水量, mm)
    を取得。

    - 同一座標は WEATHER_CACHE_TTL_SEC の間ディスクキャッシュを使い、API を呼ばない。
    - キャッシュ期限切れ後の連続取得は WEATHER_HTTP_MIN_INTERVAL_SEC で間隔を空ける。
    - 429 のときは短い待機後に最大1回だけ再試行（長い指数バックオフはしない／HTTP ワーカータイムアウト回避）。
    - 完全失敗時は期限切れキャッシュがあればそれを返す。
    """
    if not ENABLE_WEATHER:
        return None, None, None, None

    latitude = WEATHER_LAT if lat is None else float(lat)
    longitude = WEATHER_LON if lon is None else float(lon)
    key = _weather_location_key(latitude, longitude)
    now = time.time()

    disk = _load_weather_disk_cache()
    entry = disk.get(key)
    if entry:
        age = now - float(entry.get("ts", 0))
        if age >= 0 and age < WEATHER_CACHE_TTL_SEC:
            t = _tuple_from_cache_entry(entry)
            print(
                f"[weather][disk-cache] hit key={key} age_sec={age:.0f} ttl={WEATHER_CACHE_TTL_SEC}s "
                f"code={t[0]} label={t[1]}"
            )
            return t

    stale: dict | None = entry if entry else None

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "weather_code,temperature_2m,precipitation",
        "timezone": "Asia/Tokyo",
    }
    headers = {
        "User-Agent": (
            "MEGRIBI-collector/1.0 (weather; respectful use; open-meteo)"
        ),
        "Accept": "application/json",
    }

    global _last_open_meteo_http_at
    out: tuple[int | None, str | None, float | None, float | None] | None = None

    max_attempts = max(1, WEATHER_HTTP_MAX_RETRIES)
    extra_429_tries = max(0, WEATHER_429_EXTRA_TRIES)
    attempt = 0
    while attempt < max_attempts:
        _enforce_open_meteo_spacing()
        try:
            resp = requests.get(url, params=params, timeout=15, headers=headers)
            _last_open_meteo_http_at = time.time()
            if resp.status_code == 429:
                print(
                    f"[weather][429] Too Many Requests key={key} "
                    f"http_try={attempt + 1}/{max_attempts} extra_429_left={extra_429_tries}"
                )
                # 長い指数バックオフは Gunicorn の worker timeout（既定30s前後）を超えやすい
                if extra_429_tries > 0:
                    extra_429_tries -= 1
                    wait = min(8.0, max(0.5, WEATHER_429_RETRY_SLEEP_SEC))
                    print(
                        f"[weather][429] short sleep {wait:.1f}s then one retry "
                        f"(does not consume http_try budget)"
                    )
                    time.sleep(wait)
                    continue
                break

            resp.raise_for_status()
            data = resp.json()
            current = data.get("current", {})

            code = current.get("weather_code")
            temp_c = current.get("temperature_2m")
            precip_mm = current.get("precipitation")

            label = _weather_code_to_label(code) if isinstance(code, int) else None

            print(
                f"[weather] lat={latitude} lon={longitude} code={code} label={label} "
                f"temp_c={temp_c} precip_mm={precip_mm}"
            )
            disk[key] = {
                "ts": time.time(),
                "code": code,
                "label": label,
                "temp_c": temp_c,
                "precip_mm": precip_mm,
            }
            _save_weather_disk_cache(disk)
            out = (code, label, temp_c, precip_mm)
            break
        except Exception as e:
            _last_open_meteo_http_at = time.time()
            print(f"[weather][error] failed to fetch weather: {e}")
            attempt += 1
            if attempt < max_attempts:
                time.sleep(min(5.0, 1.5 * attempt))
            else:
                break

    if out is not None:
        return out

    # HTTP 失敗（429 含む）後は、ディスクキャッシュのタイムスタンプをリセットして
    # 次の収集ラン以降の即時リトライ（スノーボール）を防ぐ。
    # stale があればその値を、なければ全 None を WEATHER_CACHE_TTL_SEC 間キャッシュする。
    now_fail = time.time()
    if stale:
        t = _tuple_from_cache_entry(stale)
        print(
            f"[weather][stale-cache] using expired cache after failure key={key} code={t[0]}"
        )
        disk[key] = {
            "ts": now_fail,  # タイムスタンプを現在時刻にリセット（TTL を再スタート）
            "code": stale.get("code"),
            "label": stale.get("label"),
            "temp_c": stale.get("temp_c"),
            "precip_mm": stale.get("precip_mm"),
        }
        _save_weather_disk_cache(disk)
        return t

    # stale もない場合は None エントリを書いて 15 分間の再試行を抑制
    disk[key] = {
        "ts": now_fail,
        "code": None,
        "label": None,
        "temp_c": None,
        "precip_mm": None,
    }
    _save_weather_disk_cache(disk)
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
    *,
    brand: str = SUPABASE_BRAND,
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
        "src_brand": brand,
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


def _current_hour_window_jst() -> tuple[datetime, datetime]:
    jst = timezone(timedelta(hours=9))
    now = datetime.now(timezone.utc).astimezone(jst)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    return hour_start, hour_start + timedelta(hours=1)


def _store_has_weather_this_hour(store_id: str) -> bool:
    if not HAS_SUPABASE:
        return False
    hour_start, hour_end = _current_hour_window_jst()
    endpoint = SUPABASE_URL.rstrip("/") + "/rest/v1/logs"
    params = [
        ("select", "id"),
        ("store_id", f"eq.{store_id}"),
        ("ts", f"gte.{hour_start.isoformat()}"),
        ("ts", f"lt.{hour_end.isoformat()}"),
        ("weather_code", "not.is.null"),
        ("limit", "1"),
    ]
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }
    try:
        resp = requests.get(endpoint, params=params, headers=headers, timeout=8)
        if not resp.ok:
            return False
        payload = resp.json()
        return isinstance(payload, list) and len(payload) > 0
    except Exception:
        return False

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


# --- Bot 検知回避: User-Agent ローテーション ---
_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# --- データ検証: 店舗あたりの人数上限 ---
MAX_PEOPLE_PER_GENDER = 500  # 1店舗の男女それぞれの上限（定員超過の異常値を弾く）

# --- サイレント・フェイル検知: メンテナンス画面のキーワード ---
_MAINTENANCE_KEYWORDS = [
    "メンテナンス", "maintenance", "ただいま", "しばらくお待ち",
    "アクセスが集中", "503", "Service Unavailable", "一時的に",
    "お知らせ", "システム障害", "復旧",
]

# --- リトライ設定 ---
SCRAPE_MAX_RETRIES = int(os.getenv("SCRAPE_MAX_RETRIES", "3"))
SCRAPE_RETRY_BASE_SEC = float(os.getenv("SCRAPE_RETRY_BASE_SEC", "2.0"))


def _pick_user_agent() -> str:
    import random
    return random.choice(_USER_AGENTS)


def _detect_maintenance(html: str) -> bool:
    """200 OK だがメンテナンス画面を返しているか検知。"""
    # 人数データの存在を先にチェック（正常ページなら男性/女性の数字がある）
    if re.search(r"男性|女性|GENTLEMEN|LADIES|num-male|num-female", html):
        return False
    # 人数データがなく、メンテナンスキーワードがある → メンテナンス
    lower = html.lower()
    for kw in _MAINTENANCE_KEYWORDS:
        if kw.lower() in lower:
            return True
    # 人数データもメンテナンスキーワードもない → HTML 構造変更の可能性
    if len(html) < 1000:
        return True  # 極端に短いレスポンスは異常
    return False


def _validate_count(value: int | None, label: str, url: str) -> int | None:
    """人数データのバリデーション。異常値は None にして弾く。"""
    if value is None:
        return None
    if value < 0:
        print(f"[warn] negative count {label}={value} url={url}")
        return None
    if value > MAX_PEOPLE_PER_GENDER:
        print(f"[warn] abnormal count {label}={value} (>{MAX_PEOPLE_PER_GENDER}) url={url}")
        return None
    return value


def scrape_store(url: str) -> tuple[int | None, int | None]:
    last_err = None
    for attempt in range(1, SCRAPE_MAX_RETRIES + 1):
        try:
            return _scrape_store_once(url)
        except Exception as e:
            last_err = e
            if attempt < SCRAPE_MAX_RETRIES:
                wait = SCRAPE_RETRY_BASE_SEC * (2 ** (attempt - 1))
                print(f"[scrape] retry {attempt}/{SCRAPE_MAX_RETRIES} url={url} err={e} wait={wait:.1f}s")
                time.sleep(wait)
    print(f"[error] scrape exhausted retries url={url} last_err={last_err}")
    return None, None


def _scrape_store_once(url: str) -> tuple[int | None, int | None]:
    headers = {
        "User-Agent": _pick_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    html = resp.text

    # サイレント・フェイル検知
    if _detect_maintenance(html):
        print(f"[warn] maintenance/anomaly detected url={url} html_len={len(html)}")
        return None, None

    soup = BeautifulSoup(html, "html.parser")

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
            men = _validate_count(men, "men", url)
            women = _validate_count(women, "women", url)
            if men is not None and women is not None:
                print(f"[scrape] (new) url={url} men={men} women={women}")
                return men, women
        except Exception:
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
    men = _validate_count(men, "men", url)
    women = _validate_count(women, "women", url)

    print(f"[scrape] (fallback) url={url} men={men} women={women}")
    return men, women

# ========= アラート送信 =========


def _send_alert(message: str) -> None:
    """ALERT_WEBHOOK_URL に POST する。未設定時は何もしない。"""
    if not ALERT_WEBHOOK_URL:
        return
    try:
        requests.post(ALERT_WEBHOOK_URL, json={"text": message}, timeout=10)
        print(f"[alert] sent message={message[:80]}")
    except Exception as e:
        print(f"[alert][error] failed to send alert: {e}")


# ========= ヘルパー: 天気キー解決 =========


def _resolve_weather_key_and_coords(entry: dict) -> tuple[str, tuple[float, float]]:
    """店舗エントリから天気キャッシュキーと座標を返す。"""
    pref = entry.get("pref")
    lat = entry.get("lat")
    lon = entry.get("lon")

    if pref:
        coord = PREF_COORDS.get(pref)
        if coord:
            return pref, coord
        if lat is not None and lon is not None:
            return pref, (float(lat), float(lon))
        return pref, (WEATHER_LAT, WEATHER_LON)

    if lat is not None and lon is not None:
        return "_default", (float(lat), float(lon))
    return "_default", (WEATHER_LAT, WEATHER_LON)


# ========= Phase 1: 天気プリフェッチ =========


def _prefetch_weather(
    stores: list[dict],
) -> dict[str, tuple[int | None, str | None, float | None, float | None]]:
    """
    全店舗の天気データを事前に解決する（sequential / rate-limit 遵守）。
    返値: {store_id: (weather_code, weather_label, temp_c, precip_mm)}
    """
    result: dict[str, tuple[int | None, str | None, float | None, float | None]] = {}

    if not ENABLE_WEATHER:
        return result

    now_minute = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).minute
    hourly_window = 0 <= now_minute <= max(0, WEATHER_FETCH_WINDOW_MINUTES)
    if not hourly_window:
        print(
            f"[weather] outside hourly window minute={now_minute} "
            f"threshold={WEATHER_FETCH_WINDOW_MINUTES}"
        )
        return result

    weather_by_pref: dict[
        str, tuple[int | None, str | None, float | None, float | None]
    ] = {}
    checked_hourly: dict[str, bool] = {}

    for entry in stores:
        store_id = entry["store_id"]

        has_weather = checked_hourly.get(store_id)
        if has_weather is None:
            has_weather = _store_has_weather_this_hour(store_id)
            checked_hourly[store_id] = has_weather

        if has_weather:
            print(
                f"[weather] skip fetch store_id={store_id} minute={now_minute} "
                f"window={hourly_window} has_hourly=True"
            )
            continue

        weather_key, (lat, lon) = _resolve_weather_key_and_coords(entry)
        if weather_key not in weather_by_pref:
            weather_by_pref[weather_key] = fetch_current_weather(lat, lon)
            print(
                f"[weather][pref-cache] key={weather_key} lat={lat} lon={lon} fetched"
            )

        w = weather_by_pref[weather_key]
        result[store_id] = w
        if w[0] is not None:
            checked_hourly[store_id] = True

    return result


# ========= Phase 2: トップページ一括取得 (推奨) / 並列個別フォールバック =========

TOP_PAGE_URL = "https://oriental-lounge.com/"

# ページ ID → store_id のマッピング（stores.json の url から自動構築）
_PAGE_ID_TO_STORE_ID: dict[int, str] = {}
for _s in STORES:
    _m = re.search(r"/stores/(\d+)", _s.get("url", ""))
    if _m:
        _PAGE_ID_TO_STORE_ID[int(_m.group(1))] = _s["store_id"]


def _scrape_top_page(
    stores: list[dict],
) -> dict[str, tuple[int | None, int | None]] | None:
    """
    トップページ (oriental-lounge.com/) を 1 回のリクエストで取得し、
    全店舗の男女別人数を一括抽出する。

    38 店舗 × 個別リクエスト → 1 リクエストに最適化。
    失敗時は None を返し、呼び出し元が _parallel_scrape にフォールバックする。
    """
    try:
        headers = {
            "User-Agent": _pick_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
        resp = requests.get(TOP_PAGE_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text

        if _detect_maintenance(html):
            print("[top_page] maintenance detected, falling back to individual scraping")
            return None

        soup = BeautifulSoup(html, "html.parser")

        # トップページの店舗カード: <a href="/stores/{id}"> 内にデータが含まれる
        cards = soup.select("a[href^='/stores/']")
        if not cards:
            print("[top_page] no store cards found, falling back to individual scraping")
            return None

        # 対象 store_id のセット（フィルタ用）
        target_ids = {s["store_id"] for s in stores}
        results: dict[str, tuple[int | None, int | None]] = {}

        for card in cards:
            href = card.get("href", "")
            id_match = re.search(r"/stores/(\d+)", href)
            if not id_match:
                continue

            page_id = int(id_match.group(1))
            store_id = _PAGE_ID_TO_STORE_ID.get(page_id)
            if not store_id or store_id not in target_ids:
                continue

            # カード内テキストを平坦化して正規表現で抽出 (DOM 変更に強い)
            card_text = card.get_text(separator=" ", strip=True)
            men_match = re.search(r"(\d+)\s*GENTLEMEN", card_text, re.IGNORECASE)
            women_match = re.search(r"(\d+)\s*LADIES", card_text, re.IGNORECASE)

            men = int(men_match.group(1)) if men_match else None
            women = int(women_match.group(1)) if women_match else None

            men = _validate_count(men, "men", TOP_PAGE_URL)
            women = _validate_count(women, "women", TOP_PAGE_URL)

            results[store_id] = (men, women)

        ok = sum(1 for m, w in results.values() if m is not None and w is not None)
        total = len(target_ids)
        print(f"[top_page] extracted {ok}/{total} stores from single request")

        # 50% 未満しか取れなかった場合はフォールバック
        if ok < total * 0.5:
            print(f"[top_page] low hit rate ({ok}/{total}), falling back to individual scraping")
            return None

        # 取得できなかった店舗は (None, None) で埋める
        for s in stores:
            sid = s["store_id"]
            if sid not in results:
                results[sid] = (None, None)

        return results

    except Exception as e:
        print(f"[top_page] failed: {e}, falling back to individual scraping")
        return None


def _scrape_aisekiya() -> dict[str, tuple[int | None, int | None]]:
    """
    相席屋トップページ (aiseki-ya.com/) を 1 リクエストで取得し、
    各店舗の男女パーセンテージを抽出 → 座席数から推定人数を逆算する。

    返値: {store_id: (men, women)}
    """
    try:
        headers = {
            "User-Agent": _pick_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        resp = requests.get(AISEKIYA_TOP_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results: dict[str, tuple[int | None, int | None]] = {}
        cards = soup.select("li.p-congestionList__item")

        if not cards:
            print("[aisekiya] no store cards found")
            return results

        for card in cards:
            link = card.select_one("a.p-storeCard")
            if not link:
                continue
            href = link.get("href", "")

            # href から slug を抽出: https://aiseki-ya.com/shop/shibuya2/ → shibuya2
            slug_match = re.search(r"/shop/([^/]+)/?", href)
            if not slug_match:
                continue
            slug = slug_match.group(1)

            if slug not in AISEKIYA_STORES:
                continue

            # 男性 % を抽出
            men_node = card.select_one("dt.c-storeData__term--men")
            women_node = card.select_one("dt.c-storeData__term--women")

            men_pct = None
            women_pct = None

            if men_node:
                dd = men_node.find_next_sibling("dd")
                if dd:
                    num = dd.select_one("span.c-storeData__now")
                    if num:
                        try:
                            men_pct = int(num.get_text(strip=True))
                        except ValueError:
                            pass

            if women_node:
                dd = women_node.find_next_sibling("dd")
                if dd:
                    num = dd.select_one("span.c-storeData__now")
                    if num:
                        try:
                            women_pct = int(num.get_text(strip=True))
                        except ValueError:
                            pass

            capacity = _aisekiya_capacity(slug)
            store_id = AISEKIYA_STORES[slug]["store_id"]

            if men_pct is not None and capacity > 0:
                men = round(capacity * men_pct / 100)
            else:
                men = None

            if women_pct is not None and capacity > 0:
                women = round(capacity * women_pct / 100)
            else:
                women = None

            results[store_id] = (men, women)
            print(f"[aisekiya] {slug} men_pct={men_pct}% women_pct={women_pct}% → men={men} women={women}")

        ok = sum(1 for m, w in results.values() if m is not None and w is not None)
        print(f"[aisekiya] extracted {ok}/{len(AISEKIYA_STORES)} stores")
        return results

    except Exception as e:
        print(f"[aisekiya] scrape failed: {e}")
        return {}


def _write_aisekiya_results(
    scrape_results: dict[str, tuple[int | None, int | None]],
    weather_map: dict[str, tuple[int | None, str | None, float | None, float | None]],
) -> tuple[int, int]:
    """相席屋のスクレイピング結果を Supabase に書き込む。"""
    success = 0
    fail = 0

    for slug, info in AISEKIYA_STORES.items():
        store_id = info["store_id"]
        men, women = scrape_results.get(store_id, (None, None))

        if men is None or women is None:
            fail += 1
            continue

        # 天気は pref で引く
        pref = info.get("pref", "")
        weather_code, weather_label, temp_c, precip_mm = (None, None, None, None)
        for sid, wdata in weather_map.items():
            # Oriental Lounge の同じ pref の天気を流用
            entry = next((s for s in STORES if s.get("store_id") == sid and s.get("pref") == pref), None)
            if entry:
                weather_code, weather_label, temp_c, precip_mm = wdata
                break

        insert_supabase_log(
            store_id,
            int(men),
            int(women),
            weather_code,
            weather_label,
            temp_c,
            precip_mm,
            brand=AISEKIYA_BRAND,
        )
        success += 1

    return success, fail


def _parallel_scrape(
    stores: list[dict],
) -> dict[str, tuple[int | None, int | None]]:
    """
    ThreadPoolExecutor で全店舗を並列スクレイピングする。
    返値: {store_id: (men, women)}  — 失敗時は (None, None)
    """
    results: dict[str, tuple[int | None, int | None]] = {}
    max_workers = min(len(stores), SCRAPE_MAX_WORKERS)

    print(f"[scrape] parallel start stores={len(stores)} workers={max_workers}")
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_entry = {
            executor.submit(scrape_store, entry["url"]): entry
            for entry in stores
        }
        for future in as_completed(future_to_entry):
            entry = future_to_entry[future]
            store_id = entry["store_id"]
            store_name = entry["store"]
            try:
                men, women = future.result()
                results[store_id] = (men, women)
            except Exception as e:
                print(f"[error] scrape failed store={store_name} url={entry['url']} err={e}")
                results[store_id] = (None, None)

    elapsed = time.time() - t0
    ok = sum(1 for m, w in results.values() if m is not None and w is not None)
    print(f"[scrape] parallel done elapsed={elapsed:.1f}s ok={ok} fail={len(results) - ok}")
    return results


# ========= Phase 3: 結果書き込み =========


def _write_results(
    stores: list[dict],
    scrape_results: dict[str, tuple[int | None, int | None]],
    weather_map: dict[str, tuple[int | None, str | None, float | None, float | None]],
) -> tuple[int, int]:
    """
    スクレイピング結果を GAS + Supabase に書き込む。
    返値: (success_count, fail_count)
    """
    success = 0
    fail = 0

    for entry in stores:
        store_id = entry["store_id"]
        store_name = entry["store"]
        men, women = scrape_results.get(store_id, (None, None))

        if men is None or women is None:
            print(f"[warn] count missing store={store_name} men={men} women={women}")
            fail += 1
            continue

        weather_code, weather_label, temp_c, precip_mm = weather_map.get(
            store_id, (None, None, None, None)
        )

        # GAS（任意）
        body: dict[str, object] = {
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

        if BETWEEN_STORES_SEC > 0:
            time.sleep(BETWEEN_STORES_SEC)

        success += 1

    return success, fail


# ========= DOM 構造変更モニタリング =========


def _send_line_push(message: str) -> None:
    """LINE Messaging API で Push メッセージを送信する。"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[dom-health] LINE credentials not set, skipping push")
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    body = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=10)
        print(f"[dom-health] LINE push status={resp.status_code} body={resp.text[:200]}")
    except Exception as e:
        print(f"[dom-health][error] LINE push failed: {e}")


def _dom_alert_in_cooldown() -> bool:
    """クールダウン期間内かどうかを判定する。"""
    try:
        if _DOM_ALERT_FLAG_PATH.is_file():
            ts_str = _DOM_ALERT_FLAG_PATH.read_text(encoding="utf-8").strip()
            last_sent = float(ts_str)
            if time.time() - last_sent < DOM_ALERT_COOLDOWN_SEC:
                return True
    except Exception as e:
        print(f"[dom-health] cooldown check error: {e}")
    return False


def _mark_dom_alert_sent() -> None:
    """クールダウンフラグファイルにタイムスタンプを書き込む。"""
    try:
        _DOM_ALERT_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DOM_ALERT_FLAG_PATH.write_text(str(time.time()), encoding="utf-8")
    except Exception as e:
        print(f"[dom-health] failed to write cooldown flag: {e}")


def _check_dom_health(
    stores: list[dict],
    scrape_results: dict[str, tuple[int | None, int | None]],
) -> None:
    """
    スクレイピング結果の失敗パターンから DOM 構造変更を検知する。

    検知条件:
      1. 50% 以上の店舗で men=None かつ women=None
      2. サンプル店舗ページで主要 CSS セレクタが存在しない

    条件を満たした場合は LINE Push で通知する（6時間クールダウン付き）。
    """
    if not stores or not scrape_results:
        return

    total = len(scrape_results)
    both_none = sum(
        1 for m, w in scrape_results.values()
        if m is None and w is None
    )

    ratio = both_none / total if total > 0 else 0.0
    print(
        f"[dom-health] check: both_none={both_none}/{total} "
        f"ratio={ratio:.2f} threshold=0.50"
    )

    if ratio < 0.50:
        return  # 正常範囲

    # 追加確認: サンプル店舗ページの DOM を直接チェック
    sample_url = None
    for entry in stores:
        if entry.get("url"):
            sample_url = entry["url"]
            break

    dom_selector_missing = False
    if sample_url:
        try:
            headers = {
                "User-Agent": _pick_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            }
            resp = requests.get(sample_url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            section = soup.select_one("section[aria-label='現在の来客者数']")
            if section is None:
                dom_selector_missing = True
                print(f"[dom-health] primary CSS selector MISSING in {sample_url}")
            else:
                print(f"[dom-health] primary CSS selector found in {sample_url}")
        except Exception as e:
            print(f"[dom-health] sample page fetch error: {e}")
            # フェッチ失敗時は高失敗率だけで判断を続行する

    if not dom_selector_missing:
        # セレクタが存在する場合、DOM 変更ではなく一時的な問題の可能性
        print("[dom-health] selector present — likely transient issue, skipping alert")
        return

    # クールダウン確認
    if _dom_alert_in_cooldown():
        print("[dom-health] alert in cooldown, skipping")
        return

    # LINE Push 送信
    message = (
        f"[MEGRIBI] スクレイピング構造変更の可能性\n"
        f"{both_none}/{total}店舗でデータ取得失敗\n"
        f"確認してください: https://oriental-lounge.com/stores/38"
    )
    _send_line_push(message)
    _mark_dom_alert_sent()
    print(f"[dom-health] DOM breakage alert sent: {both_none}/{total} stores failed")


# ========= 38店舗ぶんを一気に送る =========


def collect_all_once(*, target_store_id: str | None = None) -> dict:
    """
    3-phase パイプライン:
      Phase 1 — 天気プリフェッチ (sequential, Open-Meteo rate-limit 遵守)
      Phase 2 — 38 店舗並列スクレイピング (ThreadPoolExecutor)
      Phase 3 — GAS / Supabase 書き込み (sequential)

    Returns dict with keys: stores, success, fail, duration_sec
    """
    print("collect_all_once.start")
    t_start = time.time()

    stores = STORES
    if target_store_id:
        stores = [s for s in STORES if s.get("store_id") == target_store_id]
        if not stores:
            print(f"[error] store_id not found: {target_store_id}")
            return {"stores": 0, "success": 0, "fail": 0, "duration_sec": 0}

    # Phase 1: 天気データ事前取得
    weather_map = _prefetch_weather(stores)

    # Phase 2: トップページ一括取得 → 失敗時は個別スクレイピングにフォールバック
    scrape_results = _scrape_top_page(stores)
    if scrape_results is None:
        print("[collect] top-page failed, using parallel individual scraping")
        scrape_results = _parallel_scrape(stores)

    # Phase 2.5: DOM 構造変更チェック（全店舗分のスクレイプ完了後）
    _check_dom_health(stores, scrape_results)

    # Phase 2b: 相席屋トップページ一括取得 (SSR, パーセンテージ → 逆算)
    aisekiya_results = _scrape_aisekiya()

    # Phase 3: 結果書き込み (Oriental Lounge)
    success, fail = _write_results(stores, scrape_results, weather_map)

    # Phase 3b: 相席屋の結果書き込み
    ay_success, ay_fail = _write_aisekiya_results(aisekiya_results, weather_map)
    success += ay_success
    fail += ay_fail

    duration = time.time() - t_start
    total = len(stores) + len(AISEKIYA_STORES)
    print(
        f"collect_all_once.done stores={total} success={success} fail={fail} "
        f"duration={duration:.1f}s"
    )

    # 失敗率が閾値を超えた場合はアラートを送信
    if total > 0 and fail / total >= ALERT_FAIL_RATIO_THRESHOLD:
        msg = (
            f"[MEGURIBI] 収集失敗アラート: {fail}/{total} 店舗が失敗 "
            f"(失敗率 {fail / total * 100:.0f}% / duration={duration:.1f}s)"
        )
        _send_alert(msg)

    return {"stores": total, "success": success, "fail": fail, "duration_sec": round(duration, 1)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect lounge counts and optional weather data")
    parser.add_argument("--store-id", help="process only one store_id (e.g. ol_nagasaki)")
    args = parser.parse_args()
    collect_all_once(target_store_id=args.store_id)
