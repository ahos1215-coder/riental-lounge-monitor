Write-Host "[patch] start"

# 必須フォルダ
New-Item -ItemType Directory -Force oriental\data   | Out-Null
New-Item -ItemType Directory -Force oriental\ml     | Out-Null
New-Item -ItemType Directory -Force oriental\routes | Out-Null

# 最小の forecast ルート（疎通用）
@"
from __future__ import annotations
import os
from flask import Blueprint, jsonify, request

bp = Blueprint("forecast", __name__, url_prefix="/api")

def _guard():
    return os.getenv("ENABLE_FORECAST","0") == "1"

@bp.get("/forecast_next_hour")
def next_hr():
    if not _guard():
        return jsonify({"ok": False, "error": "forecast disabled"}), 503
    return jsonify({"ok": True, "data": [{"ts":"test","men_pred":1,"women_pred":2,"total_pred":3}]})

@bp.get("/forecast_today")
def today():
    if not _guard():
        return jsonify({"ok": False, "error": "forecast disabled"}), 503
    return jsonify({"ok": True, "data": [{"ts":"test","men_pred":1,"women_pred":2,"total_pred":3}]})
"@ | Set-Content -Encoding UTF8 oriental\routes\forecast.py

# app.py に Blueprint 登録を追記（重複回避）
$apppath="app.py"
if (Test-Path $apppath) {
  $c = Get-Content $apppath -Raw
  if ($c -notmatch "routes\.forecast") {
@"
try:
    from oriental.routes.forecast import bp as forecast_bp
    app.register_blueprint(forecast_bp)
except Exception as e:
    print(f"[warn] forecast blueprint not loaded: {e}")
"@ | Add-Content -Encoding UTF8 $apppath
  }
}

Write-Host "[patch] done"
