import os
import json
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "data.json")
LOG_FILE = os.path.join(DATA_DIR, "log.jsonl")

GS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxHW688WVJIbu12LukpplzrR4QvsiygE-e8gSFpY6pETZOhHJJXth-wkm1FdmHFpC5d/exec"

# ===== Utils =====
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_log(record):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def now_jst():
    return datetime.utcnow() + timedelta(hours=9)

def save_to_google_sheets(record):
    try:
        res = requests.post(GS_WEBHOOK_URL, json=record, timeout=10)
        print("Posted to Google Sheets:", res.status_code)
    except Exception as e:
        print("Error posting to Google Sheets:", e)

# ===== Web =====
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/current")
def api_current():
    return jsonify(load_data())

# 収集：サンプルだが、URL から人数を上書きできるようにしておく
# 例) /tasks/collect?men=0&women=0   ←今の長崎0人を反映させたい時に使えます
@app.route("/tasks/collect")
def collect_task():
    men = request.args.get("men", type=int)
    women = request.args.get("women", type=int)

    # サンプル既定値（未指定なら 12/8）
    if men is None: men = 12
    if women is None: women = 8

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

# 本日分のログを返す（フロントで10分バケット化する前提）
@app.route("/api/range")
def api_range():
    start = request.args.get("from")
    end = request.args.get("to")
    limit = int(request.args.get("limit", 500))

    rows = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                ts = rec.get("ts")
                if not ts:
                    continue
                if start and ts < start:
                    continue
                if end and ts > end:
                    continue
                rows.append(rec)

    # 後方 limit 件（最新優先）
    rows = rows[-limit:]
    return jsonify({"ok": True, "rows": rows})

# 直近n日・曜日平均（ダッシュボード下段用）
@app.route("/api/summary")
def api_summary():
    days = int(request.args.get("days", 28))
    cutoff = (now_jst().date() - timedelta(days=days)).isoformat()

    rows = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("ts", "")[:10] >= cutoff:
                    rows.append(rec)

    agg = {}
    for r in rows:
        w = datetime.fromisoformat(r["ts"]).weekday()  # 0=Mon
        d = agg.setdefault(w, {"men":0,"women":0,"total":0,"count":0})
        d["men"] += r.get("men",0); d["women"] += r.get("women",0); d["total"] += r.get("total",0); d["count"] += 1
    for w,d in agg.items():
        if d["count"]:
            d["men"]/=d["count"]; d["women"]/=d["count"]; d["total"]/=d["count"]
    return jsonify(agg)

@app.route("/api/forecast")
def api_forecast():
    data = load_data()
    if not data:
        return jsonify({"ok": False, "msg": "no data"})
    forecast_total = int(data.get("total",0) * 1.2)
    return jsonify({"ok": True, "today": data.get("date"), "forecast_total": forecast_total})

# スケジューラ（10分ごと）
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
    threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    ensure_data_dir()
    start_scheduler_thread()
    app.run(debug=True, use_reloader=False)
