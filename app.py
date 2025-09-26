import os
import json
import threading
import requests
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, render_template

from bs4 import BeautifulSoup  # ← 追加

app = Flask(__name__)

# ---------- Paths ----------
DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "data.json")
LOG_FILE = os.path.join(DATA_DIR, "log.jsonl")

# ---------- Config ----------
GS_WEBHOOK_URL = os.getenv(
    "GS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbxHW688WVJIbu12LukpplzrR4QvsiygE-e8gSFpY6pETZOhHJJXth-wkm1FdmHFpC5d/exec",
)
ORIENTAL_URL = os.getenv("ORIENTAL_URL", "")  # ← 公式WebページのURL（Renderの環境変数で設定）

# ========== Utils ==========
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    ensure_data_dir()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_log(record):
    ensure_data_dir()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def now_jst():
    return datetime.utcnow() + timedelta(hours=9)

def save_to_google_sheets(record):
    if not GS_WEBHOOK_URL:
        return
    try:
        res = requests.post(GS_WEBHOOK_URL, json=record, timeout=10)
        print("Posted to Google Sheets:", res.status_code)
    except Exception as e:
        print("Error posting to Google Sheets:", e)

def parse_ymd(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

# ========== Scraper ==========
def fetch_official_data():
    """
    公式Webページ(ORIENTAL_URL)から現在人数をスクレイピングして返す。
    返り値: {"men": int, "women": int}
    """
    if not ORIENTAL_URL:
        raise RuntimeError("ORIENTAL_URL is not set")

    headers = {
        # 軽いブロック回避のためUAを偽装
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0 Safari/537.36"
    }
    r = requests.get(ORIENTAL_URL, headers=headers, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")

    # ===== ここが唯一の“要調整ポイント” =====
    # ブラウザで公式ページを開き、男/女の数字要素を右クリック→「検証」で
    # セレクタを確認して、下の selector_men / selector_women を書き換えてください。
    selector_men = "div:contains('GENTLEMEN') .some-number"   # ← 仮
    selector_women = "div:contains('LADIES') .some-number"    # ← 仮

    # 例）もし「<span class='count men'>12</span>」なら
    #   selector_men = "span.count.men"
    #   selector_women = "span.count.women"

    # 見つからなければ例外にしてログに出す
    men_el = soup.select_one(selector_men)
    women_el = soup.select_one(selector_women)
    if not men_el or not women_el:
        raise RuntimeError("Failed to locate counters with the given CSS selectors")

    def to_int(text):
        return int("".join(ch for ch in text if ch.isdigit()))

    men = to_int(men_el.get_text(strip=True))
    women = to_int(women_el.get_text(strip=True))

    return {"men": men, "women": women}

# ========== Routes ==========
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/api/current")
def api_current():
    return jsonify(load_data())

# 手動/自動収集
@app.route("/tasks/collect")
def collect_task():
    men = request.args.get("men", type=int)
    women = request.args.get("women", type=int)

    # (A) パラメータが来ていればそれを優先
    if men is None or women is None:
        # (B) それ以外はスクレイピングで取得
        try:
            data = fetch_official_data()
            men, women = data["men"], data["women"]
        except Exception as e:
            # もし取得に失敗したら、以前の値 or デフォルトで埋める
            print("fetch_official_data() error:", e)
            last = load_data()
            men = men if men is not None else last.get("men", 12)
            women = women if women is not None else last.get("women", 8)

    total = men + women
    ts = now_jst()
    record = {
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "store": "長崎",
        "men": men,
        "women": women,
        "total": total,
        "weather": None,
        "temp": None,
        "precip_mm": None,
        "ts": ts.isoformat(timespec="seconds"),
    }

    save_data(record)
    append_log(record)
    save_to_google_sheets(record)

    print(f"[{record['ts']}] Collected: {record['store']} M={men} W={women} T={total}")
    return jsonify({"ok": True, "record": record})

# 範囲取得
@app.route("/api/range")
def api_range():
    start_s = request.args.get("from")
    end_s = request.args.get("to")
    limit = int(request.args.get("limit", 500))

    today = now_jst().date()
    start_d = parse_ymd(start_s) or today
    end_d = parse_ymd(end_s) or today

    rows = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("ts")
                if not ts:
                    continue
                rec_d = datetime.fromisoformat(ts).date()
                if start_d <= rec_d <= end_d:
                    rows.append(rec)

    rows = rows[-limit:]
    return jsonify({"ok": True, "rows": rows})

# 曜日平均
@app.route("/api/summary")
def api_summary():
    days = int(request.args.get("days", 28))
    cutoff = (now_jst().date() - timedelta(days=days))

    rows = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("ts")
                if not ts:
                    continue
                if datetime.fromisoformat(ts).date() >= cutoff:
                    rows.append(rec)

    agg = {}
    for r in rows:
        w = datetime.fromisoformat(r["ts"]).weekday()
        d = agg.setdefault(w, {"men": 0, "women": 0, "total": 0, "count": 0})
        d["men"] += r.get("men", 0)
        d["women"] += r.get("women", 0)
        d["total"] += r.get("total", 0)
        d["count"] += 1
    for w, d in agg.items():
        if d["count"]:
            d["men"] /= d["count"]
            d["women"] /= d["count"]
            d["total"] /= d["count"]
    return jsonify(agg)

# ========== Scheduler ==========
_scheduler_started = False
_scheduler_lock = threading.Lock()

def scheduler_job():
    with app.app_context():
        try:
            collect_task()
        except Exception as e:
            print("Scheduler error:", e)

def start_scheduler_thread():
    def loop():
        while True:
            scheduler_job()
            threading.Event().wait(600)  # 10分
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t

@app.before_request
def _bootstrap_once():
    """最初のアクセス時だけスケジューラ起動"""
    global _scheduler_started
    ensure_data_dir()
    with _scheduler_lock:
        if not _scheduler_started:
            start_scheduler_thread()
            _scheduler_started = True
            print("[bootstrap] scheduler started")

# ---- ローカル実行用 ----
if __name__ == "__main__":
    ensure_data_dir()
    start_scheduler_thread()
    app.run(debug=True, use_reloader=False)
