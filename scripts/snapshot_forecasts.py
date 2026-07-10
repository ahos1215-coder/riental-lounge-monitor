"""Evening snapshot of tonight's SERVED forecast, for the daily answer-check loop.

Runs ~18:10 JST (before the 19:00 night starts), so it captures the pure
forward-looking forecast with no tonight-anchoring. The curve is saved to Supabase
Storage and scored against the realized counts next morning by score_forecasts.py.
This measures the LIVE forecast error — distinct from the training holdout MAE in
metadata.json / the accuracy card — and is exactly the gap that hid the
weather/skew bugs. See plan/FORECAST_ACCURACY.md.

Storage layout (reuses the existing model bucket, no new infra):
    <FORECAST_MODEL_BUCKET>/accuracy/snapshots/<YYYYMMDD>.json   (night of YYYYMMDD, JST)

Stdlib only. Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY; BACKEND_URL optional.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oriental.ml.night_type import classify_night, special_block  # noqa: E402

JST = timezone(timedelta(hours=9))
DEFAULT_BACKEND = "https://riental-lounge-monitor.onrender.com"

# v2 SHADOW: scripts/build_templates.py がここへ書く店×夜タイプのテンプレを読み、
# A スナップショットと並べて v2 予測を同じ JSON に記録する（本番配信は不変）。
TEMPLATES_PATH = "forecast/templates_v2.json"
V2_SLOTS = 40  # 19:00〜04:45 を 15 分刻みで 40 スロット（build_templates と同一）
V2_STALE_HOURS = 48  # テンプレがこれより古い/無い → v2=null（A は無傷）


def _load_env() -> None:
    for name in (".env", ".env.local"):
        p = REPO_ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _all_store_slugs() -> list[str]:
    # 全ブランド（oriental + aisekiya 等）を対象にする。相席屋も予測の答え合わせに載せる。
    path = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [s["slug"] for s in data if s.get("slug")]


def _get_json(url: str, retries: int = 3):
    last = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:160]
            if attempt < retries:
                time.sleep(3 * attempt)
    print(f"[snapshot][warn] GET failed: {url} :: {last}")
    return None


def _storage_put(bucket: str, path: str, payload: bytes, url: str, key: str) -> None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "x-upsert": "true",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30)


def _storage_get(bucket: str, path: str, url: str, key: str) -> bytes | None:
    endpoint = f"{url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            return None
        raise


def _parse_iso(s: str | None) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _store_id_for(slug: str) -> str:
    """フロント slug -> serving store_id（相席屋 ay_* はそのまま、オリエンタルは ol_ 付与）。
    score_forecasts.py と同一規約。"""
    return slug if slug.startswith("ay_") else f"ol_{slug}"


def _v2_points(t: dict, ts_list: list[datetime]) -> list[dict]:
    """テンプレ 1 タイプ分から 40 スロットの v2 予測点を組む。

    total=shape[i]×scale_ref, men=total×men_ratio[i], women=total−men,
    帯 p10[i]×scale_ref / p90[i]×scale_ref。
    """
    shape = t.get("shape") or []
    p10 = t.get("p10") or []
    p90 = t.get("p90") or []
    mr = t.get("men_ratio") or []
    scale = float(t.get("scale_ref") or 0.0)
    out: list[dict] = []
    for i, ts in enumerate(ts_list):
        sh = float(shape[i]) if i < len(shape) else 0.0
        ratio = float(mr[i]) if i < len(mr) else 0.5
        total = sh * scale
        men = total * ratio
        out.append(
            {
                "ts": ts.isoformat(),
                "total_pred": round(total, 3),
                "men_pred": round(men, 3),
                "women_pred": round(total - men, 3),
                "p10": round((float(p10[i]) if i < len(p10) else 0.0) * scale, 3),
                "p90": round((float(p90[i]) if i < len(p90) else 0.0) * scale, 3),
            }
        )
    return out


def _compute_v2(
    slugs: list[str], supabase_url: str, key: str, bucket: str, now_jst: datetime
) -> dict[str, dict | None]:
    """今夜(JST)の v2 予測を店(slug)別に組む。テンプレが無い/古い(>48h)店は None。

    A スナップショットを絶対に壊さないよう、テンプレ取得・組成の失敗はここで握りつぶし、
    その店(または全店)を v2=null にして警告だけ残す。
    """
    out: dict[str, dict | None] = {}
    try:
        raw = _storage_get(bucket, TEMPLATES_PATH, supabase_url, key)
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot][warn] v2 templates fetch failed: {str(exc)[:120]}")
        raw = None
    doc = None
    if raw is not None:
        try:
            doc = json.loads(raw.decode())
        except Exception:  # noqa: BLE001
            doc = None

    generated_at = doc.get("generated_at") if isinstance(doc, dict) else None
    gdt = _parse_iso(generated_at)
    fresh = (
        isinstance(doc, dict)
        and isinstance(doc.get("stores"), dict)
        and gdt is not None
        and (datetime.now(timezone.utc) - gdt) <= timedelta(hours=V2_STALE_HOURS)
    )
    if not fresh:
        print(f"[snapshot][warn] v2 templates missing/stale (>{V2_STALE_HOURS}h) — v2=null for all stores")
        return {slug: None for slug in slugs}

    stores = doc["stores"]
    tonight = now_jst.date()
    ntype = classify_night(tonight)
    sblock = special_block(tonight)
    base = now_jst.replace(hour=19, minute=0, second=0, microsecond=0)
    ts_list = [base + timedelta(minutes=15 * i) for i in range(V2_SLOTS)]

    for slug in slugs:
        sid = _store_id_for(slug)
        st = stores.get(sid)
        if not isinstance(st, dict) or not isinstance(st.get(ntype), dict):
            out[slug] = None
            print(f"[snapshot][warn] v2: no {ntype} template for {sid} (slug={slug})")
            continue
        t = st[ntype]
        out[slug] = {
            "night_type": ntype,
            "special_block": sblock,
            "template_generated_at": generated_at,
            "template_fallback": t.get("fallback"),
            "data": _v2_points(t, ts_list),
        }
    return out


def main() -> int:
    _load_env()
    backend = (os.environ.get("BACKEND_URL") or DEFAULT_BACKEND).rstrip("/")
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or "ml-models").strip()
    if not supabase_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    slugs = _all_store_slugs()
    night_date = datetime.now(JST).strftime("%Y%m%d")

    by_slug: dict[str, list] = {}
    for i in range(0, len(slugs), 40):  # forecast_today_multi accepts up to 40 stores
        chunk = slugs[i : i + 40]
        url = f"{backend}/api/forecast_today_multi?stores=" + urllib.parse.quote(",".join(chunk))
        data = _get_json(url)
        for slug, v in ((data or {}).get("by_slug") or {}).items():
            if isinstance(v, dict) and v.get("ok") and isinstance(v.get("data"), list):
                by_slug[slug] = [
                    {
                        "ts": p.get("ts"),
                        "total_pred": p.get("total_pred"),
                        "men_pred": p.get("men_pred"),
                        "women_pred": p.get("women_pred"),
                    }
                    for p in v["data"]
                    if isinstance(p, dict) and p.get("ts")
                ]

    # v2 SHADOW: 今夜のテンプレ予測を A と同じ JSON に併記する（キー "v2"、A は不変）。
    # 何が起きても A スナップショットを落とさない。
    try:
        v2_by_slug = _compute_v2(slugs, supabase_url, key, bucket, datetime.now(JST))
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot][warn] v2 composition failed entirely, writing v2=null: {str(exc)[:150]}")
        v2_by_slug = {slug: None for slug in slugs}
    v2_ok = sum(1 for v in v2_by_slug.values() if v)

    payload = {
        "night_date": night_date,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "stores": len(by_slug),
        "by_slug": by_slug,
        "v2": v2_by_slug,
    }
    path = f"accuracy/snapshots/{night_date}.json"
    _storage_put(bucket, path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), supabase_url, key)
    print(f"[snapshot] saved {len(by_slug)}/{len(slugs)} stores (v2 for {v2_ok}) -> {bucket}/{path}")
    if not by_slug:
        raise SystemExit("no forecasts captured (backend down or all stores empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
