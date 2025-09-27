# app.py
import os
import re
import json
import time
import requests
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, render_template
from bs4 import BeautifulSoup

app = Flask(__name__)

# ---------- Paths ----------
DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "data.json")
LOG_FILE = os.path.join(DATA_DIR, "log.jsonl")

# ---------- Config ----------
TARGET_URL   = os.getenv("TARGET_URL", "https://oriental-lounge.com/stores/38")  # 長崎店ページ
STORE_NAME   = os.getenv("STORE_NAME", "長崎")
GS_WEBHOOK_URL = os.getenv("GS_WEBHOOK_URL", "")  # Google Apps Script の /exec URL
WINDOW_START = int(os.getenv("WINDOW_START", "19"))  # 収集開始時刻(時) JST
WINDOW_END   = int(os.getenv("WINDOW_END", "3"))   # 収集終了時刻(翌日, 時) JST

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

def parse_ymd(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def save_to_google_sheets(record: dict):
    """Apps Script Webhook に JSON を POST。3回まで再試行。"""
    if not GS_WEBHOOK_URL:
        return
    payload = record
    last_err = None
    for i in range(3):
        try:
            res = requests.post(GS_WEBHOOK_URL, json=payload, timeout=10)
            print("Posted to Google Sheets:", res.status_code)
            return
        except Exception as e:
            last_err = e
            time.sleep(1.5)
    print("Error posting to Google Sheets:", last_err)

# ========== Scraper ==========
def scrape_oriental_counts() -> tuple[int | None, int | None]:
    """
    対象サイトから (men, women) を抽出。
    「28 GENTLEMEN / 26 LADIES」の表示を主にテキスト走査で検出。
    """
    try:
        resp = requests.get(TARGET_URL, timeout=12, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MonitorBot/1.0)"
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        men = None
        women = None

        # ページ全文テキストから拾う
        full_text = soup.get_text(" ", strip=True)

        # 数字の後にラベル
        m_num_before = re.search(r"(\d+)\s*(?:GENTLEMEN|Men|MEN|男性)", full_text, re.IGNORECASE)
        w_num_before = re.search(r"(\d+)\s*(?:LADIES|Women|WOMEN|女性)", full_text, re.IGNORECASE)

        # ラベルの後に数字
        m_label_before = re.search(r"(?:GENTLEMEN|Men|MEN|男性)[^\d]{0,10}(\d+)", full_text, re.IGNORECASE)
        w_label_before = re.search(r"(?:LADIES|Women|WOMEN|女性)[^\d]{0,10}(\d+)", full_text, re.IGNORECASE)

        if m_num_before:
            men = int(m_num_before.group(1))
        elif m_label_before:
            men = int(m_label_before.group(1))

        if w_num_before:
            women = int(w_num_before.group(1))
        elif w_label_before:
            women = int(w_label_before.group(1))

        # 予備: セレクタ候補
        if men is None or women is None:
            candidates_m = [
                ".men-count", ".male .count", "#menCount", "#men", ".count-men",
                '[data-role="men"]', '[data-gender="male"]'
            ]
            candidates_w = [
                ".women-count", ".female .count", "#womenCount", "#women", ".count-women",
                '[data-role="women"]', '[data-gender="female"]'
            ]
            def to_int(node):
                if not node: return None
                m = re.search(r"\d+", node.get_text(strip=True).replace(",", ""))
                return int(m.group()) if m else None
            if men is None:
                for sel in candidates_m:
                    node = soup.select_one(sel)
                    men = to_int(node)
                    if men is not None: break
            if women is None:
                for sel in candidates_w:
                    node = soup.select_one(sel)
                    women = to_int(node)
                    if women is not None: break

        return men, women
    except Exception as e:
        print("scrape error:", e)
        return (None, None)

# ========== Core collect ==========
def do_collect(men: int | None = None, women: int | None = None, source: str | None = None) -> dict:
    """
    収集の中核。men/women が与えられなければスクレイピング。
    /tasks/collect?men=..&women=.. で手動テスト値を保存可能。
    """
    if men is None or women is None:
        men_s, women_s = scrape_oriental_counts()
        men = men if men is not None else men_s
        women = women if women is not None else women_s
        source = source or TARGET_URL
    else:
        source = source or "manual"

    total = (men + women) if (men is not None and women is not None) else None

    ts = now_jst()
    record = {
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "store": STORE_NAME,
        "men": men,
        "women": women,
        "total": total,
        "weather": None,
        "temp": None,
        "precip_mm": None,
        "ts": ts.isoformat(timespec="seconds"),
        "source": source,
    }

    save_data(record)
    append_log(record)
    save_to_google_sheets(record)

    print(f"[{record['ts']}] Scraped: M={men} W={women} T={total}")
    return record

# ========== Time window ==========
def is_within_window(ts: datetime | None = None) -> bool:
    """
    収集ウィンドウ: 19:00〜翌03:00 （03:00を含む）
    """
    ts = ts or now_jst()
    hhmm = ts.hour * 60 + ts.minute
    start = WINDOW_START * 60
    end = WINDOW_END * 60
    return (hhmm >= start) or (hhmm <= end)

# ========== Routes ==========
@app.route("/")
def index():
    try:
        return render_template("index.html")
    except Exception:
        cur = load_data()
        return jsonify({"msg": "index.html が無いので JSON を返します", "current": cur})

@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/api/current")
def api_current():
    return jsonify(load_data())

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

@app.route("/tasks/collect")
def collect_task():
    men = request.args.get("men", type=int)
    women = request.args.get("women", type=int)
    rec = do_collect(men=men, women=women, source="manual" if men is not None and women is not None else None)
    return jsonify({"ok": True, "record": rec})

@app.route("/tasks/tick")
def tasks_tick():
    if not is_within_window():
        return jsonify({"ok": True, "skipped": True, "reason": "outside-window"})
    rec = do_collect()
    return jsonify({"ok": True, "record": rec})

@app.route("/tasks/seed")
def tasks_seed():
    today = now_jst().strftime("%Y-%m-%d")
    exists = False
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("date") == today:
                    exists = True
                    break
    if not exists:
        rec = do_collect()
        return jsonify({"ok": True, "seeded": True, "record": rec})
    return jsonify({"ok": True, "seeded": False})

# ---- Local run ----
if __name__ == "__main__":
    ensure_data_dir()
    app.run(debug=True, use_reloader=False)
