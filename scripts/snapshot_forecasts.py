"""Evening snapshot of tonight's SERVED forecast, for the daily answer-check loop.

Runs ~18:10 JST (before the 19:00 night starts), so it captures the pure
forward-looking forecast with no tonight-anchoring. The curve is saved to Supabase
Storage and scored against the realized counts next morning by score_forecasts.py.
This measures the LIVE forecast error — distinct from the training holdout MAE in
metadata.json / the accuracy card — and is exactly the gap that hid the
weather/skew bugs. See plan/FORECAST_ACCURACY.md.

Storage layout (reuses the existing model bucket, no new infra):
    <FORECAST_MODEL_BUCKET>/accuracy/snapshots/<YYYYMMDD>.json            (night of YYYYMMDD, JST)
    <FORECAST_MODEL_BUCKET>/accuracy/snapshots/_partial/<YYYYMMDD>.json   (診断用の退避先)

Validate-before-promote (2026-08-21, 外部レビュー F1): 期待する店舗 slug 集合が
すべて揃った夜だけを正規パスへ書く。1店でも欠けた夜は `_partial/` へ退避し、
欠落店名を出力して非ゼロ終了する（正規パスは前夜までの last-good を保持）。
payload には常に `expected_slugs` / `missing_slugs` / `captured_at_utc` を含めるので、
翌朝の score_forecasts.py は「そのスナップショット自身の件数」ではなく
`expected_slugs` を分母に coverage を判定できる。

Every payload includes `captured_at_utc` (see main() below) precisely so
score_forecasts.py can detect a late capture: if this job fires meaningfully
after 18:10 JST, tonight-anchoring may already be blending in the real-time
actuals by the time the forecast is captured, which would make the "pure
forward forecast" answer-check secretly peek at the answer. See
score_forecasts.py's module docstring (contamination detection) and
plan/FORECAST_ACCURACY.md for the full writeup.

2026-07-18 (B1): GHA `schedule:` for this job was measured to fire ~72-186min
late on 8 sampled nights (19:22-21:16 JST instead of 18:10) — the same
scheduler-throttling behavior documented in scripts/warm_cdn_local.py /
plan/CDN_WARMING_LOCAL.md (GHA `schedule:` fired only 8.3% on time there).
Migrating this job's primary execution to the owner's local Task Scheduler
(mirroring MEGRIBI-warm-cdn) is the durable fix in progress; this script
already runs standalone off .env/.env.local (stdlib only for the `by_slug`
path; the v2 composition needs `jpholiday`, already a requirements.txt dep
that the owner's PC has installed for the existing local
generate_weekly_insights.py / local_report_job.py jobs, which import the same
oriental.ml.night_type module) and needs no code change to run from Task
Scheduler — see .github/workflows/forecast-accuracy-track.yml for the
primary/backup note and the registration command.

Stdlib only. Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY; BACKEND_URL optional.
"""

from __future__ import annotations

import functools
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# scripts/_night_slots.py（40スロットグリッド定数の共有実装、stdlib のみ）を
# シブリングとしてベアインポートする。build_templates.py と同一の値であることを
# tests/test_night_slots.py で担保する。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _night_slots import SLOTS as V2_SLOTS  # noqa: E402
from _standalone_import import load_module_from_file  # noqa: E402
from _stores_common import all_slugs, slug_to_store_id  # noqa: E402
from _supabase_common import _load_env, storage_get, storage_put  # noqa: E402

# ログ接頭辞だけを固定した別名（モジュール変数名は従来どおり = 既存テストの
# monkeypatch.setattr(snap, "_storage_get", ...) がそのまま効く）。
_storage_get = functools.partial(storage_get, log_prefix="[snapshot][warn]")
_storage_put = functools.partial(storage_put, log_prefix="[snapshot][warn]")

try:
    from oriental.ml.night_type import classify_night, special_block  # noqa: E402
except ModuleNotFoundError:
    # 最小依存環境(GHA=stdlib+jpholidayのみ)ではパッケージ経由importが
    # oriental/__init__.py の flask 等を引き込んで失敗するため、ファイル直読みで代替。
    _nt = load_module_from_file("_night_type_standalone", "oriental/ml/night_type.py")
    classify_night, special_block = _nt.classify_night, _nt.special_block

JST = timezone(timedelta(hours=9))
DEFAULT_BACKEND = "https://riental-lounge-monitor.onrender.com"

# v2 SHADOW: scripts/build_templates.py がここへ書く店×夜タイプのテンプレを読み、
# A スナップショットと並べて v2 予測を同じ JSON に記録する（本番配信は不変）。
TEMPLATES_PATH = "forecast/templates_v2.json"
# V2_SLOTS は scripts/_night_slots.py で定義（build_templates.py の SLOTS と共有）。
V2_STALE_HOURS = 48  # テンプレがこれより古い/無い → v2=null（A は無傷）

# 正規パス（翌朝 score_forecasts.py が読む唯一の場所）と、不完全キャプチャの退避先。
SNAPSHOT_DIR = "accuracy/snapshots"
PARTIAL_DIR = "accuracy/snapshots/_partial"


def _all_store_slugs() -> list[str]:
    # 全ブランド（oriental + aisekiya 等）を対象にする。相席屋も予測の答え合わせに載せる。
    return all_slugs()


def _expected_slugs(slugs: list[str] | None = None) -> list[str]:
    """今夜「揃っているべき」slug 集合（＝正規パスへ昇格する条件）。

    既定は全店。恒久的に予測が出ない店が出たとき、コード変更なしで運用を止めない
    ための逃げ道として、環境変数 `SNAPSHOT_ALLOWED_MISSING`（カンマ区切りの slug）で
    期待集合から外せる。外した店は当然その夜の答え合わせ対象からも外れる。

    2026-08-21 外部レビュー F1 追補: この逃がし弁に全店の slug を並べると
    `expected=[]` になり、呼び出し元の `complete = not missing` は「欠けている店が
    無い」＝True と誤判定して、中身が空のスナップショットを正規パスへ昇格させてしまう
    （F1 の主目的「壊れた成果物を正規パスへ昇格させない」がこの経路だけ破られる）。
    ここでは空集合そのものは禁止しない（呼び出し元 main() が expected 空なら昇格させ
    ない判断をする）が、次の2点は運用者が気づけるようここで警告する:
      - 除外リストに stores.json に存在しない slug が混ざっている（打ち間違い）
      - 除外数が全店の1/4を超えている（想定より多い＝設定ミスの疑い）
    """
    base = list(slugs) if slugs is not None else _all_store_slugs()
    allowed = {s.strip() for s in (os.environ.get("SNAPSHOT_ALLOWED_MISSING") or "").split(",") if s.strip()}
    if not allowed:
        return base

    base_set = set(base)
    unknown = sorted(allowed - base_set)
    if unknown:
        print(
            "[snapshot][warn] SNAPSHOT_ALLOWED_MISSING has unknown slug(s) "
            f"(not in stores.json, check for typos): {','.join(unknown)}"
        )

    excluded = allowed & base_set
    if base and len(excluded) * 4 > len(base):
        print(
            f"[snapshot][warn] SNAPSHOT_ALLOWED_MISSING excludes {len(excluded)}/{len(base)} "
            "stores (>25%) - confirm this is intentional, not a stale/overbroad env var"
        )

    return [s for s in base if s not in allowed]


def _missing_slugs(expected: list[str], by_slug: dict[str, list]) -> list[str]:
    """期待集合のうち、使える予測点列が1点も取れなかった slug（ソート済み）。

    キー自体が無い場合だけでなく、空リスト（＝翌朝1スロットも答え合わせできない）も
    欠落として扱う。
    """
    return sorted(s for s in expected if not (by_slug.get(s) or []))


def _get_json(url: str, retries: int = 3):
    """Flask `/api/*` を叩いて JSON を返す（失敗し続けたら警告して None）。

    ★似た関数が scripts/_ollama_common.py にもある（`_get_json`、指数バックオフ・
    retries 既定 1）★。統合していないのは意図的で、想定している失敗が違うため:
      - こちら（snapshot）: 18:10 の一発勝負。Render の起き抜け 5xx を線形 3, 6 秒で
        待ち、それでも駄目なら**その店だけ諦めて次へ進む**（None を返す＝例外を投げない）。
      - _ollama_common 側: レポート本文の材料取得。呼び出し元が retries を明示した
        ときだけ再試行し、全滅時は例外を送出して呼び出し元に判断させる。
    このファイルは argparse を持たない（＝引数を付けても本番ジョブが丸ごと走る）ので
    実行確認ができず、統合の risk/benefit が釣り合わない。片方を変えるときは両方読むこと。
    """
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


def _parse_iso(s: str | None) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _store_id_for(slug: str) -> str:
    """フロント slug -> serving store_id。stores.json が正本
    （scripts/_stores_common.py）。score_forecasts.py と同一規約。"""
    return slug_to_store_id(slug)


def _v2_points(t: dict, ts_list: list[datetime], scale_override: float | None = None) -> list[dict]:
    """テンプレ 1 タイプ分から 40 スロットの v2 予測点を組む。

    total=shape[i]×scale, men=total×men_ratio[i], women=total−men,
    帯 p10[i]×scale / p90[i]×scale。scale は既定で scale_ref、v2.1 の tonight ブロックが
    有効なら scale_override(=scale_blend50) を使う（帯も同じ scale で伸縮する）。
    """
    shape = t.get("shape") or []
    p10 = t.get("p10") or []
    p90 = t.get("p90") or []
    mr = t.get("men_ratio") or []
    scale = float(scale_override) if scale_override is not None else float(t.get("scale_ref") or 0.0)
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
        print(f"[snapshot][warn] v2 templates missing/stale (>{V2_STALE_HOURS}h) - v2=null for all stores")
        return {slug: None for slug in slugs}

    stores = doc["stores"]
    tonight = now_jst.date()
    tonight_iso = tonight.isoformat()
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
        # v2.1 blend50: tonight ブロックが「今夜の日付・夜タイプ」に一致し scale_blend50 を
        # 持つときだけ採用（stale-tonight ガード）。不一致・欠如は scale_ref にフォールバック。
        scale_override = None
        scale_source = "scale_ref"
        tn = st.get("tonight")
        if (
            isinstance(tn, dict)
            and tn.get("date") == tonight_iso
            and tn.get("night_type") == ntype
            and isinstance(tn.get("scale_blend50"), (int, float))
            and not isinstance(tn.get("scale_blend50"), bool)
        ):
            scale_override = float(tn["scale_blend50"])
            scale_source = "blend50"
        out[slug] = {
            "night_type": ntype,
            "special_block": sblock,
            "template_generated_at": generated_at,
            "template_fallback": t.get("fallback"),
            "scale_source": scale_source,
            "data": _v2_points(t, ts_list, scale_override=scale_override),
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

    # 2026-08-21 外部レビュー F1: 期待集合と突き合わせ、欠けている夜は**正規パスを
    # 上書きしない**（旧実装は成功した店だけの by_slug をその夜の正規パスへ保存し、
    # 空でも保存してから exit 1 していた。翌朝の score は「その欠陥スナップショット
    # 自身の件数」を期待数にするため、空なら coverage 検査が無効化され、部分欠落なら
    # 欠けた店が分母から消える＝監視が緑のまま精度追跡に穴が空く。docs/FAILURE_MAP.md
    # 順位3の「空 snapshot が30日以上」はこの経路）。
    expected = _expected_slugs(slugs)
    missing = _missing_slugs(expected, by_slug)
    # 2026-08-21 外部レビュー F1 追補: expected が空（＝逃がし弁で全店を除外した）だと
    # missing も必ず空になり、以前は `complete = not missing` が True を返して中身空の
    # payload を正規パスへ書いていた。「期待集合が非空」を complete の必要条件に加える。
    complete = bool(expected) and not missing

    payload = {
        "night_date": night_date,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "stores": len(by_slug),
        "expected_slugs": expected,
        "missing_slugs": missing,
        "by_slug": by_slug,
        "v2": v2_by_slug,
    }
    path = f"{SNAPSHOT_DIR if complete else PARTIAL_DIR}/{night_date}.json"
    _storage_put(bucket, path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), supabase_url, key)
    print(f"[snapshot] saved {len(by_slug)}/{len(expected)} stores (v2 for {v2_ok}) -> {bucket}/{path}")
    if complete:
        return 0

    # 不完全: 正規パスは前夜までの last-good のまま残す（＝上書き破壊しない）。
    if not expected:
        print(
            f"[snapshot][ERROR] expected slug set is empty for night {night_date} "
            "(SNAPSHOT_ALLOWED_MISSING excluded every store?) -> canonical "
            f"{bucket}/{SNAPSHOT_DIR}/{night_date}.json was NOT written (kept last-good)."
        )
    else:
        print(
            f"[snapshot][ERROR] incomplete capture for night {night_date}: "
            f"{len(missing)}/{len(expected)} stores missing -> canonical "
            f"{bucket}/{SNAPSHOT_DIR}/{night_date}.json was NOT written (kept last-good). "
            f"missing={','.join(missing)}"
        )
    if not by_slug:
        print("[snapshot][ERROR] no forecasts captured at all (backend down or all stores empty)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
