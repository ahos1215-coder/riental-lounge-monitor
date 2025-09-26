import os
import json
import threading
import requests
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, render_template

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

def parse_ymd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

# --------- core (requestに依存しない) ----------
def scrape_counts():
    """
    ここに実際のスクレイプを実装。
    取得できない場合は (None, None) を返す。
    """
    return (None, None)

def collect_core(men=None, women=None):
    """
    men/women が None の場合は scrape する。
    それでも取れなければ最後の値 or 既定値で処理。
    """
    if men is None or women is None:
        s_m, s_w = scrape_counts()
        if s_m is not None and s_w is not None:
            men, women = s_m, s_w

    if men is None or women is None:
        # 最後の値か既定値
        last = load_data()
        men = men if men is not None else last.get("men", 0)
        women = women if women is not None else last.get("women", 0)

    total = int(men) + int(women)
    ts = now_jst()
    record = {
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "store": "長崎",
        "men": int(men),
        "women": int(women),
        "total": total,
        "weather": None,
        "temp": None,
        "precip_mm": None,
        "ts": ts.isoformat(timespec="seconds"),
    }

    save_data(record)
    append_log(record)
    save_to_google_sheets(record)
    print(f"[{record['ts']}] Collected: {record['store']} M={record['men']} W={record['women']} T={record['total']}")
    return record

# ========== Routes ==========
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/api/current")
def api_current():
    return jsonify(load_data())

# 手動入力：例 /tasks/collect?men=10&women=5
@app.route("/tasks/collect")
def collect_task():
    men = request.args.get("men", type=int)
    women = request.args.get("women", type=int)
    rec = collect_core(men, women)
    return jsonify({"ok": True, "record": rec})

# 自動スクレイプ（即時実行したいとき用）
@app.route("/tasks/scrape")
def scrape_task():
    rec = collect_core(None, None)
    return jsonify({"ok": True, "record": rec})

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
                d = datetime.fromisoformat(ts).date()
                if start_d <= d <= end_d:
                    rows.append(rec)

    rows = rows[-limit:]
    return jsonify({"ok": True, "rows": rows})

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
                if ts and datetime.fromisoformat(ts).date() >= cutoff:
                    rows.append(rec)

    agg = {}
    for r in rows:
        w = datetime.fromisoformat(r["ts"]).weekday()
        d = agg.setdefault(w, {"men": 0, "women": 0, "total": 0, "count": 0})
        d["men"] += r.get("men", 0)
        d["women"] += r.get("women", 0)
        d["total"] += r.get("total", 0)
        d["count"] += 1
    for d in agg.values():
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
            collect_core(None, None)  # ← requestに依存しない関数だけを呼ぶ
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
    """最初のアクセスで一度だけスケジューラを起動（WSGI対応）。"""
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
