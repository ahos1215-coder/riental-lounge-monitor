#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blend_weights（予測ブレンド重み）の凍結が本当に守られているかを独立に監視する。

2026-08-22 重み凍結（外部レビュー討議 plan/FORECAST_FREEZE_DEBATE_FINDINGS.md F-5）:
scripts/score_forecasts.py は毎晩 accuracy/scores/<date>.json を書いた後、従来は
accuracy/blend_weights.json（配信 = canonical、oriental/ml/forecast_service.py が読む）を
汚染された成績表から再計算して**上書き**していた。これを BLEND_WEIGHTS_MODE=frozen（既定）で
止め、canonical を凍結発動時点のバイト列に固定する。ただし「score が成功した」ことは
「canonical が変わっていない」ことの証明にはならない（score_forecasts.py 自身の bug・
手動実行・別経路からの書き込みで canonical が動く可能性は残る）。このスクリプトは
score ジョブの成否とは別経路で、canonical の SHA-256 が凍結発動時点のまま不変であることを
直接検証する。

Storage レイアウト（bucket 既定 FORECAST_MODEL_BUCKET=ml-models。パス文字列は
scripts/score_forecasts.py の書き手側と同一と決めた正本 —
plan/FORECAST_FREEZE_DEBATE_FINDINGS.md 冒頭の【全班共通の正本仕様】参照。
score_forecasts.py 側の実装とは相互参照コメントで対応させ、文字列自体は
（stdlib 最小依存というこのファイルの設計上）意図的に重複させている）:
    accuracy/blend_weights.json                         配信 (canonical)。凍結中は誰も書かない。
    accuracy/blend_weights_shadow/legacy.json            旧ロジックの候補値（shadow、常に書かれる）。
    accuracy/blend_weights_freeze/generations/<sha256>.json  canonical の同一バイト列のバックアップ世代。
    accuracy/blend_weights_freeze/current.json            凍結 manifest（state/freeze_id/backup_path 等）。

通常モード（引数なし・read-only。.github/workflows/check-blend-weights-freeze.yml の
schedule から6時間毎に呼ばれる）:
  a. canonical: 存在・JSON妥当・weights が dict・全値が有限かつ 0..1 → 崩れていれば失敗。
  b. manifest:
     - 無い  → 「凍結未発動」として明示ログのみ（発動前に赤くしない）。
     - state=="active"  → 世代ファイルを取得し、sha256(世代バイト列)==freeze_id かつ
       sha256(canonical バイト列)==freeze_id を検証。不一致は「凍結が破られた」ので失敗。
     - state=="inactive" → ログのみ（解除は正常フロー）。
     - それ以外の値      → 未知状態は fail-closed で失敗扱い（このプロジェクト全体の規約:
       BLEND_WEIGHTS_MODE の未知値と同じく、知らない状態を黙って緑にしない）。
  c. shadow: manifest が active かつ activated_at から30時間以上経っていれば、
     shadow.generated_at が48時間以内であること（= score ジョブが生きている証拠）。
     発動直後（30時間未満）は score が1回もまだ回っていない可能性があるので猶予する。

復元モード（--restore。workflow_dispatch の input restore=true のときだけ渡される。
schedule からは絶対に渡らない = 自動復元はしない設計）:
  manifest が active であることを確認 → 世代ファイルを取得し再検証 → canonical へ書き込み →
  read-back して hash 一致を確認。どこかで不一致なら**何も書かずに**失敗を返す。

環境変数:
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY  必須
  FORECAST_MODEL_BUCKET  Storage バケット名（既定 ml-models。oriental/config.py の既定と同じ）
  GITHUB_STEP_SUMMARY / GITHUB_OUTPUT  あれば書き込む（GHA 外では書かずに続行）

終了コード: 0 = 凍結が健全（または未発動・正常に解除済み） / 1 = 破損・不一致・照会失敗。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _supabase_common import storage_get, storage_put  # noqa: E402

# ---- Storage パス（★正本は plan/FORECAST_FREEZE_DEBATE_FINDINGS.md 冒頭の
# 【全班共通の正本仕様】。score_forecasts.py 側の書き手実装と文字列を必ず一致させること。★ ----
CANONICAL_PATH = "accuracy/blend_weights.json"
SHADOW_PATH = "accuracy/blend_weights_shadow/legacy.json"
MANIFEST_PATH = "accuracy/blend_weights_freeze/current.json"
GENERATIONS_PREFIX = "accuracy/blend_weights_freeze/generations/"

# 発動直後は score がまだ1回も回っていない可能性があるため、shadow 鮮度チェックに猶予を持たせる。
GRACE_HOURS = 30.0
# score は毎朝06:10 JST 発火の1本のみ（forecast-accuracy-track.yml）。48時間は「score が
# 1回落ちてもすぐには赤くしないが、2回連続で落ちたら気づく」ための閾値
# （check_daily_published.py 等、他の監視スクリプトの猶予設計と同じ考え方）。
SHADOW_STALE_HOURS = 48.0

Fetch = Callable[[str], bytes | None]
Put = Callable[[str, bytes], None]


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_iso(raw: object) -> datetime | None:
    """ISO8601 文字列を tz 付き UTC の datetime にする。読めない値は None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _check_canonical(raw: bytes | None) -> tuple[dict | None, list[str]]:
    """canonical の形式検証。(a) 存在・JSON妥当・weights が dict・全値有限0..1。"""
    if raw is None:
        return None, [f"canonical が見つかりません: {CANONICAL_PATH}"]
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"canonical の JSON が壊れています: {exc}"]
    if not isinstance(doc, dict):
        return None, ["canonical が JSON object ではありません"]
    weights = doc.get("weights")
    if not isinstance(weights, dict):
        return doc, ["canonical.weights が object ではありません"]
    bad: list[str] = []
    for store_id, w in weights.items():
        try:
            wf = float(w)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            bad.append(str(store_id))
            continue
        if not math.isfinite(wf) or not (0.0 <= wf <= 1.0):
            bad.append(str(store_id))
    if bad:
        shown = ", ".join(sorted(bad)[:10]) + (" ほか" if len(bad) > 10 else "")
        return doc, [f"canonical.weights に有限値/0..1範囲外の値があります: {shown}"]
    return doc, []


def _check_manifest(raw: bytes | None) -> tuple[dict | None, list[str]]:
    """manifest の形式検証のみ（state に応じた分岐は呼び出し側）。無ければ (None, []) を返す
    （未発動は問題ではないため、ここでは何も積まない）。"""
    if raw is None:
        return None, []
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"manifest の JSON が壊れています: {exc}"]
    if not isinstance(doc, dict):
        return None, ["manifest が JSON object ではありません"]
    required = ("schema", "state", "freeze_id", "activated_at", "source_generated_at", "backup_path", "store_count")
    missing = [f for f in required if f not in doc]
    if missing:
        return doc, [f"manifest に必須フィールドが欠けています: {', '.join(missing)}"]
    return doc, []


def evaluate(fetch: Fetch, now: datetime) -> tuple[str, list[str]]:
    """通常モード（read-only）の判定本体。サマリ本文と問題点一覧を返す。"""
    lines = ["blend_weights 凍結監視"]
    problems: list[str] = []

    canonical_raw = fetch(CANONICAL_PATH)
    canonical_doc, canon_problems = _check_canonical(canonical_raw)
    if canon_problems:
        lines.append("- canonical: NG (" + "; ".join(canon_problems) + ")")
        problems.extend(canon_problems)
    else:
        n_stores = len(((canonical_doc or {}).get("weights")) or {})
        lines.append(f"- canonical: OK（{n_stores} 店、形式検証パス）")

    manifest_raw = fetch(MANIFEST_PATH)
    manifest_doc, manifest_problems = _check_manifest(manifest_raw)
    if manifest_problems:
        lines.append("- manifest: NG (" + "; ".join(manifest_problems) + ")")
        problems.extend(manifest_problems)
        return "\n".join(lines), problems

    if manifest_doc is None:
        # 発動前にジョブを赤くしない（プロジェクト方針。仕様書 b. 参照）。
        lines.append("- manifest: 無し（凍結は未発動です）")
        return "\n".join(lines), problems

    state = manifest_doc.get("state")
    freeze_id = manifest_doc.get("freeze_id")
    backup_path = manifest_doc.get("backup_path")

    if state == "inactive":
        lines.append(f"- manifest: state=inactive（凍結は正常に解除済み。freeze_id={freeze_id}）")
        return "\n".join(lines), problems

    if state != "active":
        msg = f"manifest.state が未知の値です（fail-closed）: {state!r}"
        lines.append(f"- manifest: NG ({msg})")
        problems.append(msg)
        return "\n".join(lines), problems

    # --- state == "active": hash 整合性を検証する ---
    expected_backup_path = f"{GENERATIONS_PREFIX}{freeze_id}.json"
    if backup_path != expected_backup_path:
        msg = f"manifest.backup_path が freeze_id から導かれるパスと一致しません: {backup_path!r} != {expected_backup_path!r}"
        lines.append(f"- generation: NG ({msg})")
        problems.append(msg)
    else:
        generation_raw = fetch(backup_path)
        if generation_raw is None:
            msg = f"バックアップ世代が見つかりません: {backup_path}"
            lines.append(f"- generation: NG ({msg})")
            problems.append(msg)
        else:
            gen_hash = _sha256_hex(generation_raw)
            if gen_hash != freeze_id:
                msg = f"バックアップ世代の hash が freeze_id と不一致: {gen_hash} != {freeze_id}"
                lines.append(f"- generation: NG ({msg})")
                problems.append(msg)
            else:
                lines.append("- generation: OK（hash が freeze_id と一致）")

        if canonical_raw is not None:
            canon_hash = _sha256_hex(canonical_raw)
            if canon_hash != freeze_id:
                msg = f"canonical の hash が freeze_id と不一致（凍結が破られています）: {canon_hash} != {freeze_id}"
                lines.append(f"- canonical hash: NG ({msg})")
                problems.append(msg)
            else:
                lines.append(f"- canonical hash: OK（freeze_id={freeze_id} と一致、配信値は1バイトも変わっていません）")

    lines.append(
        f"- manifest: state=active, freeze_id={freeze_id}, "
        f"activated_at={manifest_doc.get('activated_at')}, store_count={manifest_doc.get('store_count')}"
    )

    # --- shadow 鮮度（= score ジョブの生存確認） ---
    activated_at = _parse_iso(manifest_doc.get("activated_at"))
    if activated_at is None:
        msg = f"manifest.activated_at を解釈できません: {manifest_doc.get('activated_at')!r}"
        lines.append(f"- shadow: 判定不能 ({msg})")
        problems.append(msg)
        return "\n".join(lines), problems

    age_since_activation_h = (now - activated_at).total_seconds() / 3600.0
    if age_since_activation_h < GRACE_HOURS:
        lines.append(
            f"- shadow: 猶予中（凍結発動から {age_since_activation_h:.1f}h、"
            f"{GRACE_HOURS:.0f}h 未満は score 未実行でも失敗にしない）"
        )
        return "\n".join(lines), problems

    shadow_raw = fetch(SHADOW_PATH)
    if shadow_raw is None:
        msg = f"shadow が見つかりません（score ジョブが動いていない疑い）: {SHADOW_PATH}"
        lines.append(f"- shadow: NG ({msg})")
        problems.append(msg)
        return "\n".join(lines), problems

    try:
        shadow_doc = json.loads(shadow_raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        msg = f"shadow の JSON が壊れています: {exc}"
        lines.append(f"- shadow: NG ({msg})")
        problems.append(msg)
        return "\n".join(lines), problems

    if not isinstance(shadow_doc, dict):
        msg = "shadow が JSON object ではありません"
        lines.append(f"- shadow: NG ({msg})")
        problems.append(msg)
        return "\n".join(lines), problems

    shadow_generated_at = _parse_iso(shadow_doc.get("generated_at"))
    if shadow_generated_at is None:
        msg = "shadow.generated_at が無いか解釈できません"
        lines.append(f"- shadow: NG ({msg})")
        problems.append(msg)
        return "\n".join(lines), problems

    shadow_age_h = (now - shadow_generated_at).total_seconds() / 3600.0
    if shadow_age_h > SHADOW_STALE_HOURS:
        msg = f"shadow が古すぎます（score ジョブ停止の疑い）: {shadow_age_h:.1f}h > {SHADOW_STALE_HOURS:.0f}h"
        lines.append(f"- shadow: NG ({msg})")
        problems.append(msg)
    else:
        lines.append(f"- shadow: OK（{shadow_age_h:.1f}h 前に更新、score ジョブは生存しています）")

    return "\n".join(lines), problems


def restore(fetch: Fetch, put: Put, now: datetime) -> tuple[str, int]:
    """復元モード（--restore）。検証をすべて通ったときだけ canonical へ書く。

    どこかで不一致が見つかった時点で即座に中止し、canonical には一切触れない
    （「検証してから書く」の順序を厳守する。書いた後の read-back 不一致だけは
    書き込み自体は実行済みなので取り消せないが、exit 1 にして異常を隠さない）。
    """
    lines = ["blend_weights 凍結 復元（--restore）"]

    manifest_raw = fetch(MANIFEST_PATH)
    manifest_doc, manifest_problems = _check_manifest(manifest_raw)
    if manifest_problems:
        lines.append(f"復元中止: manifest が壊れています（{'; '.join(manifest_problems)}）")
        return "\n".join(lines), 1
    if manifest_doc is None:
        lines.append("復元中止: manifest が見つかりません（凍結が発動していません）")
        return "\n".join(lines), 1
    if manifest_doc.get("state") != "active":
        lines.append(f"復元中止: manifest.state が active ではありません（{manifest_doc.get('state')!r}）")
        return "\n".join(lines), 1

    freeze_id = manifest_doc.get("freeze_id")
    backup_path = manifest_doc.get("backup_path")
    expected_backup_path = f"{GENERATIONS_PREFIX}{freeze_id}.json"
    if backup_path != expected_backup_path:
        lines.append(
            f"復元中止: backup_path が freeze_id と一致しません（{backup_path!r} != {expected_backup_path!r}）"
        )
        return "\n".join(lines), 1

    generation_raw = fetch(backup_path)
    if generation_raw is None:
        lines.append(f"復元中止: バックアップ世代が見つかりません（{backup_path}）")
        return "\n".join(lines), 1
    if _sha256_hex(generation_raw) != freeze_id:
        lines.append("復元中止: バックアップ世代の hash が freeze_id と不一致です")
        return "\n".join(lines), 1

    lines.append(f"検証OK: バックアップ世代の hash が freeze_id と一致（{freeze_id}）。canonical へ書き込みます。")
    put(CANONICAL_PATH, generation_raw)

    readback = fetch(CANONICAL_PATH)
    if readback is None or _sha256_hex(readback) != freeze_id:
        lines.append(
            "警告: 書き込み後の read-back で hash が一致しません（書き込み自体は実行済み。要手動確認）"
        )
        return "\n".join(lines), 1

    lines.append(f"復元完了: canonical の hash が freeze_id と一致（read-back 確認済み、{CANONICAL_PATH}）")
    return "\n".join(lines), 0


def _append_env_file(env_name: str, text: str) -> None:
    """GHA が用意するファイル（GITHUB_STEP_SUMMARY 等）に追記する。無ければ何もしない。"""
    path = os.environ.get(env_name)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="blend_weights 凍結の監視・復元")
    parser.add_argument(
        "--restore",
        action="store_true",
        help="canonical を最新のバックアップ世代から検証付きで復元する（workflow_dispatch 専用。schedule からは渡さない）",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not url or not key:
        print("::error::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY secret 未設定")
        return 1
    bucket = (os.environ.get("FORECAST_MODEL_BUCKET") or "ml-models").strip()

    def fetch(path: str) -> bytes | None:
        return storage_get(bucket, path, url, key, log_prefix="[blend-freeze]")

    def put(path: str, data: bytes) -> None:
        storage_put(bucket, path, data, url, key, log_prefix="[blend-freeze]")

    try:
        if args.restore:
            detail, code = restore(fetch, put, datetime.now(timezone.utc))
        else:
            detail, problems = evaluate(fetch, datetime.now(timezone.utc))
            code = 1 if problems else 0
    except Exception as exc:  # noqa: BLE001 — Storage 通信断など。fail-closed で赤くする
        print(f"::error::Storage 照会に失敗しました: {exc}")
        return 1

    _append_env_file("GITHUB_STEP_SUMMARY", detail + "\n")
    _append_env_file("GITHUB_OUTPUT", "detail<<EOF\n" + detail + "\nEOF\n")
    print(detail)

    if code:
        print("::error::blend_weights 凍結の監視/復元でエラーが検出されました。")
    else:
        print("OK")
    return code


if __name__ == "__main__":
    sys.exit(main())
