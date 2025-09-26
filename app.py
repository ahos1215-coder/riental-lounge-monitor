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
# 環境変数があれば優先（Render に置くとき用）
GS_WEBHOOK_URL = os.getenv(
    "GS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbxHW688WVJIbu12LukpplzrR4QvsiygE-e8gSFpY6pETZOhHJJXth-wkm1FdmHFpC5d/exec",
)

# ========== Utils ==========
def ensure_data_dir():
    """データフォルダの作成（存在しなければ）。WSGIでも必ず呼ばれるように、モジュール読み込み時および
    before_first_request から呼び出す。"""
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
    """'YYYY-MM-DD' → date。失敗したら None。"""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

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

# 収集：URLクエリで人数上書き可
# 例) /tasks/collect?men=0&women=0
@app.route("/tasks/collect")
def collect_task():
    men = request.args.get("men", type=int)
    women = request.args.get("women", type=int)

    # 既定値（未指定なら 12/8）
    if men is None:
        men = 12
    if women is None:
        women = 8

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

    print(f"[{record['ts']}] Collected: {record['store']} total={record['total']}")
    return jsonify({"ok": True, "record": record})

# 本日分のログ（もしくは from/to 範囲）を返す
# 例) /api/range?from=2025-09-26&to=2025-09-26&limit=1000
@app.route("/api/range")
def api_range():
    start_s = request.args.get("from")
    end_s = request.args.get("to")
    limit = int(request.args.get("limit", 500))

    # 既定は「今日」
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
                ts = rec.get("ts")  # "YYYY-MM-DDTHH:MM:SS"
                if not ts:
                    continue
                # 日付部分だけで比較
                rec_d = datetime.fromisoformat(ts).date()
                if rec_d < start_d or rec_d > end_d:
                    continue
                rows.append(rec)

    rows = rows[-limit:]  # 後ろlimit件（新しい順でほしい場合は並べ替えも可）
    return jsonify({"ok": True, "rows": rows})

# 直近n日・曜日平均（ダッシュボード下段用）
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
        w = datetime.fromisoformat(r["ts"]).weekday()  # 0=Mon
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

@app.route("/api/forecast")
def api_forecast():
    data = load_data()
    if not data:
        return jsonify({"ok": False, "msg": "no data"})
    forecast_total = int(data.get("total", 0) * 1.2)
    return jsonify({"ok": True, "today": data.get("date"), "forecast_total": forecast_total})

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
    """10分ごとに collect を回すループを1つだけ起動。"""
    def loop():
        while True:
            scheduler_job()
            threading.Event().wait(600)  # 10分
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t

@app.before_first_request
def _bootstrap_on_wsgi():
    """gunicornなどWSGIでも、最初のリクエスト時に一度だけ初期化。"""
    global _scheduler_started
    ensure_data_dir()
    with _scheduler_lock:
        if not _scheduler_started:
            start_scheduler_thread()
            _scheduler_started = True
            print("[bootstrap] scheduler started")

# ---- ローカル実行用（python app.py） ----
if __name__ == "__main__":
    ensure_data_dir()
    start_scheduler_thread()
    app.run(debug=True, use_reloader=False)
