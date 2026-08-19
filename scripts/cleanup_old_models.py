"""Supabase Storage の ML モデル世代整理スクリプト（bucket既定 ml-models、prefix既定 forecast/latest）。

2026-08-18夜、オーケストレーターが計測: `forecast/latest` 配下が 8,200オブジェクト/1,233MB
に達し、Supabase 無料プランの1GBクォータを超過（org全体使用量1.5GB、0.5GBオーバー、
2026-09-05 に利用制限予告）。原因は `scripts/train_ml_model.py` の毎日の再学習が
「日付入りモデルファイル」を42店舗×男女=84個/日アップロードし続け、古い世代を一切
削除していなかったこと（117世代が生き残っていた: 20260324〜20260808）。

--- オブジェクト命名規約（train_ml_model.py 実物で確認済み） -----------------------
  1. 日付入り世代ファイル（毎日アップロード、絶対に自動削除されない・蓄積源）:
       model_<store_id>_<YYYYMMDD>_men.txt
       model_<store_id>_<YYYYMMDD>_women.txt
     date_tag は学習run単位で1回だけ計算され(main()内 `date_tag = ...strftime("%Y%m%d")`)、
     その run で(再)学習された全店舗に共通で使われる。つまり「世代」= 1 UTC日付。
  2. 店舗ごとの非日付エイリアス（x-upsert=true で毎回同名上書き、蓄積しない）:
       model_<store_id>_men.txt / model_<store_id>_women.txt
     "Latest alias for simpler rollback/fallback" というコメント付きでアップロードされるが、
     `oriental/ml/model_registry.py::_resolve_model_names` → `_pick_latest_model_name` は
     ファイル名に埋め込まれた日付でスコアリングするため、日付入りファイルが常に非日付
     エイリアスに勝つ（date_score>0 vs 0）。つまり実際の配信は基本的に日付入りファイルを
     読む。エイリアスは古いmetadata/障害時のフォールバック用として残す＝**絶対に削除しない**。
  3. グローバル非日付エイリアス（store_models 非対応の後方互換専用、蓄積しない）:
       model_men.txt / model_women.txt
     このrunで(再)学習された店舗のうち1店（アルファベット順先頭）の内容がコピーされる。
     **絶対に削除しない**。
  4. metadata.json: 現在配信中のモデル一覧（`store_models[store_id]` に各店の
     `model_men`/`model_women`/`dated_model_men`/`dated_model_women` を持つ）。**絶対に削除しない**。

--- 「現在使用中」の定義 ------------------------------------------------------------
  metadata.json の `store_models` に列挙されている全ファイル名（エイリアスだけでなく
  `dated_model_men`/`dated_model_women` も含む）。carry-forward の仕組み上、ある店舗が
  何日も再学習に失敗/skipし続けると、metadata が指す世代は「最新7世代」の外にあり得る
  （belt-and-braces: 世代の新旧に関わらず metadata が指す限り絶対に消さない）。

--- 閉店店舗のゴミ (sapporo_ag / ay_niigata) ----------------------------------------
  両店は `oriental/utils/stores.py::ALL_STORE_IDS` から既に除外済み。
  `scripts/train_ml_model.py::_filter_store_models_to_allowlist`（2026-07-18 Fable監査
  fix #16a）により、metadata.json の store_models/metrics は毎run allow-list に収束する
  ため、これらの店舗の日付入りファイルは現在の metadata.json から一切参照されない。
  本スクリプトは「参照されているか」だけで判定するため、特別扱い不要でそのまま削除対象
  になる（新しいスキームの世代内に閉店店舗のファイルが紛れ込むことは、閉店後は新規
  アップロードが発生しないため理論上ありえない）。

--- 保持ポリシー --------------------------------------------------------------------
  「最新 MODEL_RETENTION_GENERATIONS 世代（既定7）」+「metadata.json が参照する全ファイル」
  + 「非日付エイリアス/metadata.json 自体（無条件）」以外の日付入りファイルを削除する。

Usage:
    python scripts/cleanup_old_models.py                    # dry-run（既定・削除しない）
    python scripts/cleanup_old_models.py --execute           # 実行
    python scripts/cleanup_old_models.py --execute --retention 10

環境変数:
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY   (必須)
    FORECAST_MODEL_BUCKET          (既定 ml-models)
    FORECAST_MODEL_PREFIX          (既定 forecast/latest)
    MODEL_RETENTION_GENERATIONS    保持する世代数（既定 7）
    MODEL_CLEANUP_RETRIES          Storage呼び出しのリトライ回数（既定 8）
    MODEL_CLEANUP_BACKOFF_MAX_SEC  リトライ間隔の上限秒（既定 45）
    MODEL_CLEANUP_DELETE_BATCH_SIZE 一括削除のバッチサイズ（既定 100）
    MODEL_CLEANUP_MAX_DELETE_FRACTION 削除許容率のサニティ上限（既定 0.95）

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]

# scripts/_supabase_common.py（.env 読み込み・SUPABASE 設定解決の共有実装）を
# ベアインポートする（モジュールのdocstringに書かれている規約に合わせる）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _retry_common import backoff_delay, is_retryable_status  # noqa: E402
from _supabase_common import _load_env, _supabase_conf, auth_headers  # noqa: E402

# --- オブジェクト名の分類パターン ---------------------------------------------------
# 日付入り世代ファイル。store 部分は greedy `.+` だが、店舗idに8桁連続数字は存在しない
# ため `_<YYYYMMDD>_(men|women).txt` の直前で確実に区切れる（stores.json 全42店で確認済み）。
_DATED_RE = re.compile(r"^model_(?P<store>.+)_(?P<date>\d{8})_(?P<sex>men|women)\.txt$")
# 店舗ごとの非日付エイリアス（上の日付入りパターンに一致しなかったもののみ、順序で保証）。
_ALIAS_RE = re.compile(r"^model_(?P<store>.+)_(?P<sex>men|women)\.txt$")
_GLOBAL_ALIAS_NAMES = frozenset({"model_men.txt", "model_women.txt"})
_METADATA_NAME = "metadata.json"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# is_retryable_status / backoff_delay は scripts/_retry_common.py の共有実装。
# Storage の list/delete は軽量なメタデータ操作であり、`oriental/clients/http.py` の
# 2026-08-18「500除外」修正が対象とした「巨大クエリの statement タイムアウトが
# gunicorn スレッドを占有する」問題とはシナリオが異なる独立プロセスのバッチ処理なので、
# ここでは 500 も再試行してよい。


@dataclass(slots=True)
class ObjectInfo:
    name: str  # prefix を含まないファイル名のみ（Storage list API の仕様）
    size_bytes: int


@dataclass(slots=True)
class CleanupConfig:
    supabase_url: str
    supabase_key: str
    bucket: str
    prefix: str
    retention_generations: int = 7
    list_page_size: int = 100
    delete_batch_size: int = 100
    retries: int = 8
    backoff_max_sec: float = 45.0
    max_delete_fraction: float = 0.95

    @classmethod
    def from_env(cls) -> "CleanupConfig":
        conf = _supabase_conf()
        if conf is None:
            raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SERVICE_KEY) are required")
        url, key = conf
        return cls(
            supabase_url=url,
            supabase_key=key,
            bucket=os.getenv("FORECAST_MODEL_BUCKET", "ml-models").strip(),
            prefix=os.getenv("FORECAST_MODEL_PREFIX", "forecast/latest").strip().strip("/"),
            retention_generations=_env_int("MODEL_RETENTION_GENERATIONS", 7),
            list_page_size=_env_int("MODEL_CLEANUP_LIST_PAGE_SIZE", 100),
            delete_batch_size=_env_int("MODEL_CLEANUP_DELETE_BATCH_SIZE", 100),
            retries=_env_int("MODEL_CLEANUP_RETRIES", 8),
            backoff_max_sec=_env_float("MODEL_CLEANUP_BACKOFF_MAX_SEC", 45.0),
            max_delete_fraction=_env_float("MODEL_CLEANUP_MAX_DELETE_FRACTION", 0.95),
        )

    def validate(self) -> None:
        if not self.supabase_url or not self.supabase_key:
            raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are required")
        if not self.bucket or not self.prefix:
            raise SystemExit("FORECAST_MODEL_BUCKET / FORECAST_MODEL_PREFIX are required")
        if self.retention_generations < 1:
            raise SystemExit("MODEL_RETENTION_GENERATIONS must be >= 1")
        if self.list_page_size < 1:
            self.list_page_size = 1
        if self.list_page_size > 100:
            # Storage list API は1リクエスト最大100件（task指示どおりのハード上限）。
            print(f"  [warn] MODEL_CLEANUP_LIST_PAGE_SIZE={self.list_page_size} > 100; clamping to 100")
            self.list_page_size = 100
        if self.delete_batch_size < 1:
            self.delete_batch_size = 1
        if not (0.0 < self.max_delete_fraction <= 1.0):
            raise SystemExit("MODEL_CLEANUP_MAX_DELETE_FRACTION must be within (0, 1]")


def _headers(cfg: CleanupConfig, *, content_type: str | None = None) -> dict[str, str]:
    # Content-Type は任意の MIME（Storage の DELETE/POST は application/json）なので、
    # 共通ヘルパーの bool フラグではなく呼び出し側の文字列をそのまま載せる。
    headers = auth_headers(cfg.supabase_key)
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _storage_request(req: Request, *, cfg: CleanupConfig, what: str) -> bytes:
    """Storage呼び出しを指数バックオフ付きで再試行する（scripts/cleanup_old_logs.py の
    `_rest_request` と同型のパターン）。"""
    last = ""
    for attempt in range(1, cfg.retries + 1):
        try:
            with urlopen(req, timeout=90) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if not is_retryable_status(exc.code):
                raise
        except Exception as exc:  # noqa: BLE001 - transient network error
            last = f"{type(exc).__name__}: {str(exc)[:150]}"
        if attempt < cfg.retries:
            wait = backoff_delay(attempt, cfg.backoff_max_sec)
            print(f"  [retry] {what}: transient error ({last}); attempt {attempt}/{cfg.retries}, waiting {wait:.0f}s")
            time.sleep(wait)
    raise SystemExit(f"[error] {what} failed after {cfg.retries} attempts: {last}")


def list_all_objects(cfg: CleanupConfig) -> list[ObjectInfo]:
    """`<prefix>/` 直下の全オブジェクトを列挙する（100件/頁でページング、サブフォルダ無し
    前提のフラットなレイアウト）。"""
    endpoint = f"{cfg.supabase_url}/storage/v1/object/list/{cfg.bucket}"
    objects: list[ObjectInfo] = []
    offset = 0
    while True:
        body = json.dumps(
            {
                "prefix": cfg.prefix,
                "limit": cfg.list_page_size,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
        ).encode("utf-8")
        req = Request(endpoint, data=body, method="POST", headers=_headers(cfg, content_type="application/json"))
        raw = _storage_request(req, cfg=cfg, what=f"list objects offset={offset}")
        page = json.loads(raw)
        if not isinstance(page, list):
            raise SystemExit(f"[error] unexpected Storage list response (not a list): {str(page)[:200]}")
        if not page:
            break
        for entry in page:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name or entry.get("id") is None:
                # フォルダ・プレースホルダエントリ（このバケットのフラットなレイアウトでは
                # 想定外だが、念のためスキップして安全側に倒す＝削除候補にしない）。
                continue
            meta = entry.get("metadata") or {}
            size = meta.get("size")
            if not isinstance(size, (int, float)):
                size = meta.get("contentLength") or 0
            objects.append(ObjectInfo(name=str(name), size_bytes=int(size)))
        if len(page) < cfg.list_page_size:
            break
        offset += cfg.list_page_size
    return objects


def fetch_current_metadata(cfg: CleanupConfig) -> dict[str, Any]:
    """現在配信中の metadata.json を取得する。取得できなければ即 abort する（削除対象の
    安全判定は metadata.json の参照情報に依存するため、それが無い状態での削除実行は
    絶対に許容しない設計）。"""
    endpoint = f"{cfg.supabase_url}/storage/v1/object/{cfg.bucket}/{cfg.prefix}/{_METADATA_NAME}"
    req = Request(endpoint, headers=_headers(cfg))
    raw = _storage_request(req, cfg=cfg, what="GET metadata.json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[error] metadata.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("[error] metadata.json must be a JSON object")
    return data


def referenced_object_names(metadata: dict[str, Any]) -> set[str]:
    """metadata.json が参照している全オブジェクト名を集める（belt-and-braces: 世代が
    最新N世代の外でも、metadata が指している限り絶対に消さない）。"""
    referenced: set[str] = {_METADATA_NAME}
    for key in ("model_men", "model_women"):
        val = metadata.get(key)
        if isinstance(val, str) and val:
            referenced.add(val)
    store_models = metadata.get("store_models")
    if isinstance(store_models, dict):
        for entry in store_models.values():
            if not isinstance(entry, dict):
                continue
            for key in ("model_men", "model_women", "dated_model_men", "dated_model_women"):
                val = entry.get(key)
                if isinstance(val, str) and val:
                    referenced.add(val)
    return referenced


@dataclass(slots=True)
class Classification:
    kind: str  # "generation" | "alias" | "metadata" | "unknown"
    date_tag: str | None = None


def classify(name: str) -> Classification:
    if name == _METADATA_NAME:
        return Classification(kind="metadata")
    m = _DATED_RE.match(name)
    if m:
        return Classification(kind="generation", date_tag=m.group("date"))
    if name in _GLOBAL_ALIAS_NAMES:
        return Classification(kind="alias")
    if _ALIAS_RE.match(name):
        return Classification(kind="alias")
    return Classification(kind="unknown")


@dataclass(slots=True)
class RetentionPlan:
    total_objects: int
    total_size_bytes: int
    generations: dict[str, list[ObjectInfo]]
    keep_dates: set[str]
    delete_names: list[str]  # full paths (prefix/name), ready for the delete API
    delete_size_bytes: int
    kept_generation_objects: int
    alias_count: int
    unknown_names: list[str]
    referenced: set[str]


def build_plan(objects: list[ObjectInfo], metadata: dict[str, Any], cfg: CleanupConfig) -> RetentionPlan:
    referenced = referenced_object_names(metadata)
    generations: dict[str, list[ObjectInfo]] = {}
    alias_count = 0
    unknown_names: list[str] = []

    for obj in objects:
        c = classify(obj.name)
        if c.kind == "generation":
            generations.setdefault(c.date_tag, []).append(obj)
        elif c.kind in ("alias", "metadata"):
            alias_count += 1
        else:
            unknown_names.append(obj.name)

    sorted_dates = sorted(generations.keys(), reverse=True)
    keep_dates = set(sorted_dates[: cfg.retention_generations])

    delete_names: list[str] = []
    delete_size = 0
    kept_generation_objects = 0
    for date_tag, objs in generations.items():
        for obj in objs:
            must_keep = date_tag in keep_dates or obj.name in referenced
            if must_keep:
                kept_generation_objects += 1
                continue
            delete_names.append(f"{cfg.prefix}/{obj.name}")
            delete_size += obj.size_bytes

    total_size = sum(o.size_bytes for o in objects)

    return RetentionPlan(
        total_objects=len(objects),
        total_size_bytes=total_size,
        generations=generations,
        keep_dates=keep_dates,
        delete_names=delete_names,
        delete_size_bytes=delete_size,
        kept_generation_objects=kept_generation_objects,
        alias_count=alias_count,
        unknown_names=unknown_names,
        referenced=referenced,
    )


def assert_plan_safety(plan: RetentionPlan, cfg: CleanupConfig) -> None:
    """安全弁（belt-and-braces）: 削除リストが「参照済みオブジェクト」「保持世代」の
    いずれも含んでいないことを実行直前に再検証する（build_plan 自体にバグがあった場合の
    最後の防波堤）。加えて削除率が sanity 上限を超えていないかも確認する。
    dry-run/execute どちらでも必ず呼ぶ（dry-runの結果自体が「実行しても安全か」を
    表すため）。"""
    delete_set = set(plan.delete_names)
    for date_tag in plan.keep_dates:
        for obj in plan.generations.get(date_tag, []):
            full = f"{cfg.prefix}/{obj.name}"
            assert full not in delete_set, (
                f"SAFETY VIOLATION: {full} belongs to a KEPT generation ({date_tag}) but is in the delete set"
            )
    for ref_name in plan.referenced:
        full = f"{cfg.prefix}/{ref_name}"
        assert full not in delete_set, (
            f"SAFETY VIOLATION: {full} is referenced by metadata.json but is in the delete set"
        )
    if plan.total_objects > 0:
        frac = len(plan.delete_names) / plan.total_objects
        if frac > cfg.max_delete_fraction:
            raise SystemExit(
                f"[abort] delete-set is {frac:.1%} of all objects (> {cfg.max_delete_fraction:.0%} sanity cap); "
                "refusing to proceed. Investigate MODEL_RETENTION_GENERATIONS / metadata.json before overriding."
            )


def delete_objects(names: list[str], cfg: CleanupConfig) -> int:
    """Storage オブジェクトを ~100件ずつバッチ削除する
    (DELETE /storage/v1/object/<bucket> body={"prefixes": [...]})。"""
    if not names:
        return 0
    endpoint = f"{cfg.supabase_url}/storage/v1/object/{cfg.bucket}"
    deleted = 0
    for i in range(0, len(names), cfg.delete_batch_size):
        batch = names[i : i + cfg.delete_batch_size]
        body = json.dumps({"prefixes": batch}).encode("utf-8")
        req = Request(endpoint, data=body, method="DELETE", headers=_headers(cfg, content_type="application/json"))
        batch_no = i // cfg.delete_batch_size + 1
        _storage_request(req, cfg=cfg, what=f"delete batch {batch_no} ({len(batch)} objects)")
        deleted += len(batch)
        print(f"  [delete] batch {batch_no}: {len(batch)} objects (total {deleted}/{len(names)})")
    return deleted


def _write_delete_list_file(plan: RetentionPlan) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(tempfile.gettempdir()) / f"megribi_model_cleanup_delete_list_{ts}.txt"
    lines = [f"# {len(plan.delete_names)} objects, {plan.delete_size_bytes / 1024 / 1024:.1f} MB"]
    lines.extend(sorted(plan.delete_names))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _print_summary(plan: RetentionPlan, cfg: CleanupConfig, dry_run: bool) -> None:
    kept_generations = sorted(plan.keep_dates, reverse=True)
    deleted_generations = sorted(set(plan.generations) - plan.keep_dates, reverse=True)
    print("=== Model retention cleanup: forecast/latest ===")
    print(f"  mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")
    print(f"  bucket/prefix: {cfg.bucket}/{cfg.prefix}")
    print(f"  retention_generations: {cfg.retention_generations}")
    print(f"  total objects: {plan.total_objects} ({plan.total_size_bytes / 1024 / 1024:.1f} MB)")
    print(f"  generations found: {len(plan.generations)}")
    print(f"  generations kept ({len(kept_generations)}): {kept_generations}")
    print(
        f"  generations to delete ({len(deleted_generations)}): "
        f"{deleted_generations[:5]}{' ...' if len(deleted_generations) > 5 else ''}"
    )
    print(f"  alias/metadata objects kept (always): {plan.alias_count}")
    print(f"  generation-file objects kept (newest-N + metadata-referenced): {plan.kept_generation_objects}")
    print(f"  distinct object names referenced by metadata.json: {len(plan.referenced)}")
    if plan.unknown_names:
        print(f"  [WARNING] {len(plan.unknown_names)} unrecognized object name(s) -- kept, NOT deleted:")
        for n in plan.unknown_names[:20]:
            print(f"    ? {n}")
    print(f"  objects to delete: {len(plan.delete_names)} ({plan.delete_size_bytes / 1024 / 1024:.1f} MB)")
    print(f"  objects remaining after cleanup: {plan.total_objects - len(plan.delete_names)}")


def run_cleanup(cfg: CleanupConfig, *, dry_run: bool) -> RetentionPlan:
    cfg.validate()
    objects = list_all_objects(cfg)
    metadata = fetch_current_metadata(cfg)
    plan = build_plan(objects, metadata, cfg)
    assert_plan_safety(plan, cfg)
    _print_summary(plan, cfg, dry_run)
    if dry_run:
        out_path = _write_delete_list_file(plan)
        print(f"  (dry-run) full delete-list written to: {out_path}")
        print("  (dry-run complete -- use --execute to apply)")
    else:
        if plan.delete_names:
            deleted = delete_objects(plan.delete_names, cfg)
            print(f"  deleted {deleted} objects ({plan.delete_size_bytes / 1024 / 1024:.1f} MB freed)")
        else:
            print("  nothing to delete")
    return plan


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Prune old dated model generations from Supabase Storage.")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default: dry-run)")
    parser.add_argument("--retention", type=int, help="override MODEL_RETENTION_GENERATIONS")
    args = parser.parse_args()

    cfg = CleanupConfig.from_env()
    if args.retention is not None:
        cfg.retention_generations = args.retention

    run_cleanup(cfg, dry_run=not args.execute)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
