"""/api/forecast_accuracy, /api/forecast_snapshot — 予測の答え合わせ系ハンドラ。

forecast.py から機械的に分離（B8 route split）。ハンドラは `.forecast` の
Blueprint `bp`（url_prefix="/api"）にそのまま生えるため、URL / エンドポイント名は
一切変わらない。Supabase Storage から実測精度 / 過去スナップショットを読む専用ヘルパー
（_storage_get / _realized_night_avg_by_store / _night_avg_by_store / _augment_relative_fields
など）もここに集約する。
"""

from __future__ import annotations

import re

from flask import current_app, jsonify, request

from ..config import AppConfig
from ..utils.stores import SLUG_TO_ID
from .common import get_config as _config
from .forecast import bp

# /api/forecast_snapshot の date パラメータ（夜の JST 日付）。YYYYMMDD の8桁固定。
_NIGHT_DATE_RE = re.compile(r"^\d{8}$")


def _storage_get(cfg: AppConfig, path: str) -> bytes | None:
    """Supabase Storage から生バイト列を取得する共通ヘルパー。

    `_fetch_live_accuracy`（/api/forecast_accuracy）と `_fetch_forecast_snapshot`
    （/api/forecast_snapshot）の両方から使う。オブジェクトが存在しない場合
    （404、または Supabase が返す 400 の "not found" 系エラー）は None を返し、
    それ以外の HTTP エラーは呼び出し側に伝播させる（呼び出し側で握りつぶす）。
    """
    import urllib.error
    import urllib.request

    supabase_url = (cfg.supabase_url or "").rstrip("/")
    key = cfg.supabase_service_role_key or ""
    bucket = cfg.forecast_model_bucket or "ml-models"
    if not supabase_url or not key:
        return None

    endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{path}"
    req = urllib.request.Request(
        endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 400:
            try:
                body = exc.read().decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                body = ""
            if "not_found" in body or "not found" in body or "object not found" in body:
                return None
        raise


def _is_num(v: object) -> bool:
    """bool を除いた実数か（JSON 由来の int/float を想定）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _night_avg_by_store(snapshot: dict | None) -> dict[str, float]:
    """予測スナップショット (accuracy/snapshots/<date>.json の by_slug) から、
    店舗ごとの「その夜の予測総数の平均」を返す。

    rank3 fix (2026-07): これは「予測」総数の平均であり、店舗規模の近似としては
    自己参照バグを持つ（過大予測している店ほど分母が大きくなり、relative_mae が
    不当に小さく＝高精度に見える）。そのため通常経路では使わず、
    _realized_night_avg_by_store（実測ベース）が使えない**旧フォーマットのスコアに
    対する一時的なフォールバックとしてのみ**残す（_fetch_live_accuracy 参照）。

    キーは snapshot 側と同じ slug（オリエンタルは "ol_" なしの短縮 slug、相席屋は "ay_*"）。
    予測点が無い/壊れている店は結果に含めない。純関数（ネットワーク I/O 無し）。
    """
    if not isinstance(snapshot, dict):
        return {}
    by_slug = snapshot.get("by_slug")
    if not isinstance(by_slug, dict):
        return {}
    out: dict[str, float] = {}
    for slug, points in by_slug.items():
        if not isinstance(points, list):
            continue
        vals = [
            float(p.get("total_pred"))
            for p in points
            if isinstance(p, dict) and _is_num(p.get("total_pred"))
        ]
        if vals:
            out[slug] = sum(vals) / len(vals)
    return out


def _realized_night_avg_by_store(per_store: dict | None) -> dict[str, float]:
    """夜間スコア (accuracy/scores/<date>.json の per_store, scripts/score_forecasts.py が
    additive に書く `realized_night_avg`) から、店舗ごとの「実測(REALIZED)夜間平均」を
    取り出す。live_mae と同じマッチ済みスロット群の実測値平均なので、予測が過大/過少でも
    分母が歪まない（= rank3 fix の本体。_night_avg_by_store の自己参照を解消する）。

    `realized_night_avg` が無い（この修正より前に書かれた古いスコアファイル）店は
    結果に含めない。呼び出し側はその店だけ _night_avg_by_store の予測平均にフォールバック
    する（transition: 新しい夜のスコアが溜まるほど自己修復する）。純関数。
    """
    if not isinstance(per_store, dict):
        return {}
    out: dict[str, float] = {}
    for slug, entry in per_store.items():
        if not isinstance(entry, dict):
            continue
        v = entry.get("realized_night_avg")
        if _is_num(v) and v > 0:
            out[slug] = float(v)
    return out


def _augment_relative_fields(
    per_store: dict,
    night_avg: dict[str, float],
    night_avg_source: dict[str, str] | None = None,
) -> None:
    """per_store の各エントリに「店舗規模で正規化した相対性能」シグナルを追加する
    （additive・in-place、既存キーは触らない）。

    - beats_baseline: live_mae < live_baseline_mae（ナイーブ基準＝先週同時刻に勝っているか）。
      規模に依存しない頑健なシグナルで、両値が揃うときのみ付与する。
    - night_avg: 想定夜間来客数（スケール正規化の分母）。night_avg にエントリがある店のみ。
    - night_avg_source: night_avg の由来。"realized"（実測ベース、正しい）か
      "predicted"（旧フォーマットからの一時フォールバック）かを透過的に示す（additive）。
      呼び出し側が渡さない場合は "predicted" 扱い（既存呼び出し元との後方互換）。
    - relative_mae: live_mae / night_avg（店舗規模で正規化した相対誤差）。night_avg があるときのみ。

    これにより精度バッジを「絶対人数」ではなく「相対性能」で判定できる（小規模店が
    小さい MAE だけで "高精度" になり、大規模店が同等以上の相対精度でも "参考値" に
    なる逆転を解消する）。
    """
    if not isinstance(per_store, dict):
        return
    source_map = night_avg_source or {}
    for slug, entry in per_store.items():
        if not isinstance(entry, dict):
            continue
        lm = entry.get("live_mae")
        bm = entry.get("live_baseline_mae")
        if _is_num(lm) and _is_num(bm):
            entry["beats_baseline"] = bool(lm < bm)
        avg = night_avg.get(slug)
        if _is_num(avg) and avg > 0:
            entry["night_avg"] = round(float(avg), 2)
            entry["night_avg_source"] = source_map.get(slug, "predicted")
            if _is_num(lm):
                entry["relative_mae"] = round(float(lm) / float(avg), 3)


def _fetch_live_accuracy(cfg: AppConfig) -> dict | None:
    """Supabase Storage の答え合わせ結果 (scripts/score_forecasts.py が毎晩書き込む)
    から実測精度を組み立てる。summary.json が無い/壊れている、または nights が
    空なら None を返す（呼び出し側は holdout の metrics にフォールバックする）。
    Storage 障害でエンドポイント全体を落とさないよう、例外はすべてここで握りつぶす。
    """
    import json

    try:
        raw = _storage_get(cfg, "accuracy/scores/summary.json")
        if raw is None:
            return None
        summary = json.loads(raw.decode())
        nights = summary.get("nights")
        if not isinstance(nights, list) or not nights:
            return None

        def _avg(key_name: str, n: int) -> float | None:
            vals = [
                x.get(key_name) for x in nights[:n]
                if isinstance(x.get(key_name), (int, float))
            ]
            return round(sum(vals) / len(vals), 2) if vals else None

        # mae_30d は「本当に30夜以上」蓄積されるまで null にする。7夜しか無いのに
        # mae_7d と同値を「30日平均」と称するのは不誠実なラベルになるため。
        # フロントは nights_count と合わせて「n=X夜」表示にフォールバックする。
        n_nights = len(nights)
        live: dict = {
            "mae_7d": _avg("overall_live_mae", 7),
            "mae_30d": _avg("overall_live_mae", 30) if n_nights >= 30 else None,
            "baseline_7d": _avg("overall_baseline_mae", 7),
            "nights_count": n_nights,
            "updated_at": summary.get("updated_at_utc"),
            "stores_scored_latest": nights[0].get("stores_scored"),
            "per_store": {},
        }

        latest_date = nights[0].get("night_date")
        if latest_date:
            daily_raw = _storage_get(cfg, f"accuracy/scores/{latest_date}.json")
            if daily_raw is not None:
                daily = json.loads(daily_raw.decode())
                per_store = daily.get("per_store")
                if isinstance(per_store, dict):
                    live["per_store"] = per_store

        # 追加(後方互換): 店舗規模で正規化した相対性能シグナル（beats_baseline /
        # night_avg / relative_mae / night_avg_source）を per_store に付与する。
        #
        # rank3 fix (2026-07): 分母の「想定夜間来客数」は本来 実測(REALIZED) の夜間平均を
        # 使う（scripts/score_forecasts.py が同じ日次スコアに additive で書く
        # `realized_night_avg`）。過大予測している店ほど分母が膨らんで不当に高精度化する
        # 自己参照バグ（旧: 予測スナップショットの総数平均を分母にしていた）を解消する。
        #
        # Graceful transition: この修正より前に書かれた古いスコアファイルには
        # `realized_night_avg` が無いため、そういう店だけ一時的に予測スナップショットの
        # 総数平均へフォールバックする（Storage read はフォールバックが要る店が
        # 1店でもある場合のみ発生＝自己修復後は追加読み込みも消える）。
        # night_avg_source: "realized"|"predicted" でどちらを使ったかを常に明示する。
        if live["per_store"] and latest_date:
            realized_avg = _realized_night_avg_by_store(live["per_store"])
            missing_realized = [s for s in live["per_store"] if s not in realized_avg]

            predicted_avg: dict[str, float] = {}
            if missing_realized:
                try:
                    snap_raw = _storage_get(cfg, f"accuracy/snapshots/{latest_date}.json")
                    if snap_raw is not None:
                        predicted_avg = _night_avg_by_store(json.loads(snap_raw.decode()))
                except Exception:  # noqa: BLE001 — スナップショット取得/解析失敗は相対誤差なしで続行
                    predicted_avg = {}

            night_avg: dict[str, float] = {}
            night_avg_source: dict[str, str] = {}
            for slug in live["per_store"]:
                if slug in realized_avg:
                    night_avg[slug] = realized_avg[slug]
                    night_avg_source[slug] = "realized"
                elif slug in predicted_avg:
                    night_avg[slug] = predicted_avg[slug]
                    night_avg_source[slug] = "predicted"
            _augment_relative_fields(live["per_store"], night_avg, night_avg_source)

        return live
    except Exception:  # noqa: BLE001
        # Storage 障害・パース失敗は「実測精度なし」として holdout にフォールバックさせる
        current_app.logger.warning("api_forecast_accuracy.live_fetch_failed", exc_info=True)
        return None


def _fetch_forecast_snapshot(cfg: AppConfig, date: str) -> dict | None:
    """その夜（JST, YYYYMMDD）に実際に配信されていた予測のスナップショットを読み込む。

    scripts/snapshot_forecasts.py が毎晩 ~18:10 JST（夜が始まる前）に
    `<bucket>/accuracy/snapshots/<date>.json` として保存したものをそのまま返す。
    ファイルが無い（まだ書き込まれていない新しい夜 / この機能導入前の古い夜）、
    または壊れている場合は None を返す（呼び出し側は ok:false として扱い、
    実測グラフのみ表示にフォールバックする＝エラーではない）。
    """
    import json

    try:
        raw = _storage_get(cfg, f"accuracy/snapshots/{date}.json")
        if raw is None:
            return None
        return json.loads(raw.decode())
    except Exception:  # noqa: BLE001
        current_app.logger.warning(
            "api_forecast_snapshot.fetch_failed date=%s", date, exc_info=True
        )
        return None


@bp.get("/forecast_accuracy")
def api_forecast_accuracy():
    """Return per-store accuracy: 学習時の holdout metrics（後方互換）に加え、
    Supabase Storage に蓄積された本番の答え合わせ結果（live）を返す。
    """
    import json
    from pathlib import Path

    cfg = _config()
    cache_dir = Path(cfg.forecast_model_cache_dir)
    metadata_path = cache_dir / "metadata.json"

    if not metadata_path.exists():
        return jsonify({"ok": False, "error": "metadata-not-found"}), 404

    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "metadata-parse-error"}), 500

    metrics = meta.get("metrics")
    if not metrics:
        return jsonify({"ok": False, "error": "no-metrics-in-metadata"}), 404

    live = _fetch_live_accuracy(cfg)

    return jsonify({
        "ok": True,
        "trained_at": meta.get("trained_at"),
        "metrics": metrics,
        "live": live,
    })


@bp.get("/forecast_snapshot")
def api_forecast_snapshot():
    """完了済みの夜（昨日・先週・カスタムの過去日、または今日モードで既に夜が
    終わっている場合）に「実際にその夜配信されていた予測」を返す、答え合わせ用
    オーバーレイ。/api/forecast_today は常に "これからの夜" しか返さないため、
    終わった夜の予測を後から見るにはこのスナップショット（毎晩 ~18:10 JST に
    scripts/snapshot_forecasts.py が保存）を読むしかない。

    ?store=<slug>&date=<YYYYMMDD> （date は対象の夜の JST 開始日＝19:00 側の日付）。

    スナップショットが無い（対象の夜がまだ新しすぎる/この機能導入前で記録が無い）
    場合は ok:false・HTTP 200 を返す（エラーではなく「無いのが正常」なケース）。
    store/date が不正な場合のみ 400。
    """
    cfg = _config()

    store = (request.args.get("store") or "").strip().lower()
    date = (request.args.get("date") or "").strip()

    if store not in SLUG_TO_ID:
        return jsonify({"ok": False, "error": "invalid-store"}), 400
    if not _NIGHT_DATE_RE.match(date):
        return jsonify({"ok": False, "error": "invalid-date"}), 400

    snapshot = _fetch_forecast_snapshot(cfg, date)
    by_slug = snapshot.get("by_slug") if isinstance(snapshot, dict) else None
    data = by_slug.get(store) if isinstance(by_slug, dict) else None

    if not isinstance(data, list):
        current_app.logger.info(
            "api_forecast_snapshot.missing store=%s date=%s", store, date
        )
        resp = jsonify({"ok": False, "date": date, "data": []})
    else:
        current_app.logger.info(
            "api_forecast_snapshot.success store=%s date=%s points=%d",
            store, date, len(data),
        )
        resp = jsonify({"ok": True, "date": date, "data": data})

    # 過去の夜のスナップショットは不変（もう書き換わらない）→ 長め CDN キャッシュ。
    # ok:false（未記録）も含め、同じ date は将来も同じ結果になるため一緒に長くキャッシュしてよい。
    resp.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"
    return resp
