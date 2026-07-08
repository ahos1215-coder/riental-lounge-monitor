#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MEGRIBI 日次レポート生成ジョブ（ローカルLLM版）

目的:
  失敗している Gemini パイプラインを置き換え、ローカルの Ollama (gemma3n:e4b) で
  日次レポート（今夜の見どころ）を生成し、Supabase の blog_drafts テーブルに書き込む。

参照実装（このファイルはこれらを踏襲する）:
  - scripts/generate_weekly_insights.py の _upsert_weekly_report_to_supabase
    （SUPABASE エンドポイント・service_role ヘッダー・facts_id での
    PATCH→無ければ POST という idempotent upsert パターン）を厳密にミラーする。
  - scripts/experiments/local_llm_spike.py の fetch_store_facts / facts_block /
    run_ollama（Ollama /api/chat, keep_alive:0）/ SYSTEM プロンプト / gpu_lock
    の取り込み方。

使い方:
  python scripts/local_report_job.py --kind daily --stores shibuya,shinjuku \
      --edition evening_preview --mode dry-run

  --mode dry-run  (デフォルト): 生成のみ。書き込み予定の完全なレコードを表示するだけで
                   Supabase には一切触れない。
  --mode shadow  : 書き込みは行うが is_published は常に False に強制する（実験用）。
  --mode publish : 成功/失敗に応じた本番の is_published で実際に書き込む。

安全設計 (#16/#17 由来):
  生成が成功（本文が空でない）した場合のみ is_published=True かつ error_message=None。
  facts 取得失敗・Ollama 失敗・空出力など、あらゆる失敗時は is_published=False,
  error_message=<理由>, mdx_content="" とする。この2状態以外は作らない。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_JSON_PATH = REPO_ROOT / "frontend" / "src" / "data" / "stores.json"
EXPERIMENTS_DIR = REPO_ROOT / "scripts" / "experiments"

# scripts/experiments/local_llm_spike.py から facts 取得・Ollama 呼び出し・SYSTEM を再利用する。
sys.path.insert(0, str(EXPERIMENTS_DIR))
import local_llm_spike as spk  # noqa: E402  (経路追加後に import する必要がある)

# 共有GPUロック（音楽PJと衝突しないための排他）。local_llm_spike と同じ取り込み方。
try:
    sys.path.insert(0, r"C:\Users\Public\共有データ系")
    import gpu_lock  # type: ignore
except Exception:  # noqa: BLE001
    gpu_lock = None

JST = timezone(timedelta(hours=9))
MODEL = "gemma3n:e4b"
DEFAULT_USER_AGENT = "MEGRIBI-local-report-job"
VALID_EDITIONS = ("evening_preview", "late_update")
VALID_MODES = ("dry-run", "shadow", "publish")

# tune_local_llm.py (自己改善ハーネス) が書き出す推奨設定。存在すれば生成時に適用する。
# 2026-07-08: モデルを gemma3n:e4b に変更。省メモリ設計で実行時 VRAM 3.0GB・100% GPU。
# num_gpu=999 で全層 GPU を明示 (tuning_results.json が無くても下の or で常に適用)。
# num_ctx は既定 8192 のままで余裕。旧 gemma4:12b は 7.9GB でギリギリ CPU に溢れていた。
TUNING_RESULTS_PATH = Path(__file__).resolve().parents[1] / "local_llm_spike_out" / "tuning_results.json"


def _load_tuned_options() -> dict[str, Any] | None:
    """ハーネスの推奨 options を読む。無い/壊れている/モデル不一致なら None (=従来既定)。"""
    try:
        data = json.loads(TUNING_RESULTS_PATH.read_text(encoding="utf-8"))
        reco = data.get("recommended") or {}
        if reco.get("model") == MODEL and isinstance(reco.get("options"), dict):
            return dict(reco["options"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _pr(*parts: Any) -> None:
    """コンソール出力は ASCII のみとする制約があるため、日本語等の非ASCII文字は
    \\uXXXX にエスケープして print する（Windows の cp932 コンソールでの文字化け対策）。
    内容は失われず、ログから復元可能（json.loads 等で戻せる）。"""
    text = " ".join(str(p) for p in parts)
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


# ---------------------------------------------------------------------------
# .env / .env.local 読み込み（scripts/backup_logs.py と同じ手動パーサ。
# 実環境変数（GitHub Actions secrets 等）が最優先）
# ---------------------------------------------------------------------------

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


def _supabase_conf() -> tuple[str, str] | None:
    """generate_weekly_insights.py の _supabase_conf と同じ探索順。キー自体は絶対に表示しない。"""
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )
    if not base or not key:
        return None
    return base, key


# ---------------------------------------------------------------------------
# stores.json: slug -> store_id / 表示名(label) の対応表
# ---------------------------------------------------------------------------

def _load_store_map() -> dict[str, dict[str, Any]]:
    if not STORES_JSON_PATH.is_file():
        raise SystemExit(f"stores.json not found: {STORES_JSON_PATH}")
    data = json.loads(STORES_JSON_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for row in data:
        slug = row.get("slug")
        if slug:
            out[slug] = row
    return out


def _store_display_name(row: dict[str, Any]) -> str:
    """店舗の日本語表示名。ブランドに応じて prefix を付ける（label はカタカナ・漢字のまま使う）。"""
    label = row.get("label") or row.get("store") or row.get("slug") or ""
    brand = row.get("brand")
    if brand == "aisekiya":
        return f"相席屋 {label}"
    return f"オリエンタルラウンジ {label}"


def _store_id_for(row: dict[str, Any]) -> str:
    """store_id は stores.json の値をそのまま使う（ay_* を ol_ prefix にすり替えない）。"""
    store_id = row.get("store_id")
    if store_id:
        return str(store_id)
    # フォールバック（stores.json に store_id が無い想定外ケース）
    slug = row.get("slug") or ""
    brand = row.get("brand")
    return slug if brand == "aisekiya" else f"ol_{slug}"


# ---------------------------------------------------------------------------
# 日次レポート用プロンプト（週次用の prompt_weekly は「週次」と書いてしまうため使わない）
# ---------------------------------------------------------------------------

def prompt_daily(store_label: str, facts: dict[str, Any]) -> str:
    return (
        f"次のデータは相席ラウンジ「{store_label}」の現在の混雑状況と今夜の予測です。\n\n"
        f"{spk.facts_block(facts, store_label)}\n\n"
        "これをもとに、今夜これから来店を検討している人向けに、"
        "150〜300字程度の短い日次レポートを書いてください。"
        "見出し(#)から始め、今夜の混雑の見通しと『いつ頃行くと良さそうか』を"
        "数字に基づいて具体的に示唆してください。週次のまとめではなく、"
        "あくまで「今夜」の話として書くこと。前置き・言い訳・メタ発言は書かない。"
    )


# ---------------------------------------------------------------------------
# mdx_content 組み立て（frontmatter + body）
# ---------------------------------------------------------------------------

def _extract_title_and_description(body: str) -> tuple[str, str]:
    """本文の1行目の見出しから title を、本文から description を作る。"""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    title = ""
    if lines:
        first = lines[0].strip()
        if first.startswith("#"):
            title = first.lstrip("#").strip()
    if not title:
        title = lines[0].strip() if lines else "MEGRIBI 日次レポート"

    description = ""
    body_lines = lines[1:] if lines and lines[0].strip().startswith("#") else lines
    if body_lines:
        # 先頭の非見出し行から一文目を description にする（句点まで、無ければ全体）。
        candidate = body_lines[0].strip()
        idx = candidate.find("。")
        description = candidate[: idx + 1] if idx != -1 else candidate
    if not description:
        description = title
    return title, description


def _build_mdx_content(*, slug: str, facts_id: str, target_date: str, body: str) -> str:
    title, description = _extract_title_and_description(body)
    # frontmatter の値に含まれると壊れる文字（改行・二重引用符）を除去。
    def _clean(s: str) -> str:
        return s.replace("\n", " ").replace('"', "'").strip()

    frontmatter = (
        "---\n"
        f"title: \"{_clean(title)}\"\n"
        f"description: \"{_clean(description)}\"\n"
        f"date: \"{target_date}\"\n"
        "categoryId: prediction\n"
        "level: easy\n"
        f"store: {slug}\n"
        f"facts_id: {facts_id}\n"
        "facts_visibility: show\n"
        "---\n"
    )
    return frontmatter + "\n" + body.strip() + "\n"


# ---------------------------------------------------------------------------
# レコード組み立て（成功/失敗の2状態のみ。#16/#17 セーフティ）
# ---------------------------------------------------------------------------

def _failure_record(
    slug: str, store_row: dict[str, Any], edition: str, target_date: str, reason: str
) -> dict[str, Any]:
    """生成に到達できなかった場合の失敗レコード（#16/#17: is_published=False）。
    ロック取得タイムアウト等、build_record の外で起きた例外用。"""
    return {
        "store_id": _store_id_for(store_row),
        "store_slug": slug,
        "target_date": target_date,
        "facts_id": f"auto_{slug}_{edition}",
        "insight_json": {},
        "source": "local_gemma_daily",
        "content_type": "daily",
        "edition": edition,
        "public_slug": None,
        "line_user_id": None,
        "mdx_content": "",
        "is_published": False,
        "error_message": reason,
    }


def build_record(
    *,
    slug: str,
    store_row: dict[str, Any],
    edition: str,
    target_date: str,
) -> dict[str, Any]:
    facts_id = f"auto_{slug}_{edition}"
    store_id = _store_id_for(store_row)
    store_label = _store_display_name(store_row)

    base = {
        "store_id": store_id,
        "store_slug": slug,
        "target_date": target_date,
        "facts_id": facts_id,
        "insight_json": {},
        "source": "local_gemma_daily",
        "content_type": "daily",
        "edition": edition,
        "public_slug": None,
        "line_user_id": None,
    }

    # 1) facts 取得
    try:
        facts = spk.fetch_store_facts(slug)
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "mdx_content": "",
            "is_published": False,
            "error_message": f"facts fetch failed: {exc}",
        }

    # 実データが一切取れずサンプル値へフォールバックした場合は絶対に公開しない。
    # (旧条件は「両方エラー かつ source がフォールバックでない」だったが、両方エラーの
    #  ときは fetch_store_facts が必ず source="sample(fallback)" を立てるため一度も
    #  発動しない死にコードで、架空数値のレポートが公開される穴になっていた)
    if facts.get("source") == "sample(fallback)":
        return {
            **base,
            "mdx_content": "",
            "is_published": False,
            "error_message": (
                f"facts fetch failed (sample fallback): megribi={facts.get('megribi_error')} "
                f"forecast={facts.get('forecast_error')}"
            ),
        }

    # 2) Ollama 生成（呼び出し側で gpu_lock を取得済みの前提）
    user_prompt = prompt_daily(store_label, facts)
    tuned = _load_tuned_options() or {"num_gpu": 999}
    text, elapsed, err = spk.run_ollama(MODEL, spk.SYSTEM, user_prompt, options=tuned)
    if err and tuned and "num_gpu" in tuned:
        # 全層 GPU 強制 (num_gpu) は VRAM が他プロセスに部分占有されていると
        # ロード失敗し得るため、安全既定 (Ollama 自動配分) で 1 回だけ再試行する。
        _pr(f"[local-report] tuned options failed ({err[:120]}); retrying with default options")
        text, elapsed, err = spk.run_ollama(MODEL, spk.SYSTEM, user_prompt)

    if err or not text or not text.strip():
        reason = err or "empty output from ollama"
        return {
            **base,
            "mdx_content": "",
            "is_published": False,
            "error_message": f"ollama generation failed: {reason}",
        }

    # 3) 成功: mdx_content 組み立て
    mdx_content = _build_mdx_content(
        slug=slug, facts_id=facts_id, target_date=target_date, body=text.strip()
    )
    return {
        **base,
        "mdx_content": mdx_content,
        "is_published": True,
        "error_message": None,
        "_debug_elapsed_sec": round(elapsed, 1),
        "_debug_facts_source": facts.get("source"),
    }


# ---------------------------------------------------------------------------
# Supabase upsert（generate_weekly_insights.py の _upsert_weekly_report_to_supabase
# と同じエンドポイント・ヘッダー・PATCH→無ければ POST のパターンを厳密にミラー）
# ---------------------------------------------------------------------------

def _upsert_daily_report_to_supabase(record: dict[str, Any]) -> None:
    conf = _supabase_conf()
    if conf is None:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY is required for daily sync")
    base, key = conf
    endpoint = f"{base}/rest/v1/blog_drafts"
    facts_id = record["facts_id"]

    body = {
        "store_id": record["store_id"],
        "store_slug": record["store_slug"],
        "target_date": record["target_date"],
        "facts_id": facts_id,
        "mdx_content": record["mdx_content"],
        "insight_json": record["insight_json"],
        "source": record["source"],
        "content_type": record["content_type"],
        "is_published": record["is_published"],
        "edition": record["edition"],
        "public_slug": record["public_slug"],
        "line_user_id": record["line_user_id"],
        "error_message": record["error_message"],
    }
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    patch_url = f"{endpoint}?facts_id=eq.{facts_id}"
    patch_req = Request(
        patch_url,
        data=json.dumps(body, ensure_ascii=True).encode("utf-8"),
        headers=headers,
        method="PATCH",
    )
    with urlopen(patch_req, timeout=30) as resp:
        patch_raw = resp.read().decode("utf-8")
    try:
        patch_rows = json.loads(patch_raw)
    except json.JSONDecodeError:
        patch_rows = []
    if isinstance(patch_rows, list) and len(patch_rows) > 0:
        return

    insert_body = dict(body)
    insert_body["id"] = str(uuid.uuid4())
    insert_req = Request(
        endpoint,
        data=json.dumps(insert_body, ensure_ascii=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(insert_req, timeout=30):
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_store_list(value: str | None) -> list[str]:
    if not value:
        return []
    raw = value.replace(",", " ").split()
    return [item.strip() for item in raw if item.strip()]


def _print_record(slug: str, record: dict[str, Any]) -> None:
    _pr("=" * 78)
    _pr(f"[store] {slug}")
    _pr(f"  store_id      : {record['store_id']}")
    _pr(f"  store_slug    : {record['store_slug']}")
    _pr(f"  target_date   : {record['target_date']}")
    _pr(f"  facts_id      : {record['facts_id']}")
    _pr(f"  content_type  : {record['content_type']}")
    _pr(f"  edition       : {record['edition']}")
    _pr(f"  source        : {record['source']}")
    _pr(f"  public_slug   : {record['public_slug']}")
    _pr(f"  line_user_id  : {record['line_user_id']}")
    _pr(f"  is_published  : {record['is_published']}")
    _pr(f"  error_message : {record['error_message']}")
    if record.get("_debug_facts_source"):
        _pr(f"  (debug) facts_source : {record['_debug_facts_source']}")
    if record.get("_debug_elapsed_sec") is not None:
        _pr(f"  (debug) ollama_sec   : {record['_debug_elapsed_sec']}")
    _pr("  --- mdx_content -----------------------------------------------------")
    _pr(record["mdx_content"] if record["mdx_content"] else "(empty)")
    _pr("  -----------------------------------------------------------------------")


def main() -> int:
    parser = argparse.ArgumentParser(description="MEGRIBI daily report job (local LLM)")
    parser.add_argument("--kind", default="daily", choices=["daily"], help="report kind (only 'daily' supported)")
    parser.add_argument("--stores", required=True, help="comma/space separated slugs (e.g. shibuya,shinjuku) or 'all' for every store in stores.json")
    parser.add_argument("--edition", required=True, choices=VALID_EDITIONS, help="evening_preview or late_update")
    parser.add_argument("--mode", default="dry-run", choices=VALID_MODES, help="dry-run (default) / shadow / publish")
    args = parser.parse_args()

    _load_env()
    store_map = _load_store_map()

    if args.stores.strip().lower() == "all":
        slugs = list(store_map.keys())
    else:
        slugs = _parse_store_list(args.stores)
    if not slugs:
        print("[ERROR] --stores is empty", file=sys.stderr)
        return 1

    unknown = [s for s in slugs if s not in store_map]
    if unknown:
        print(f"[ERROR] unknown slug(s) not found in stores.json: {unknown}", file=sys.stderr)
        return 1

    if args.mode in ("shadow", "publish"):
        conf = _supabase_conf()
        if conf is None:
            print(
                "[ERROR] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set "
                "(.env.local) -- required for shadow/publish mode",
                file=sys.stderr,
            )
            return 1

    target_date = datetime.now(JST).strftime("%Y-%m-%d")
    _pr(f"[info] mode={args.mode} edition={args.edition} target_date={target_date} stores={slugs}")

    # gpu_lock は「店舗ごと」に取得/解放する（各レポート生成後に GPU を手放し、
    # 音楽PJがバッチの合間に割り込めるようにする＝共有GPUの良き市民）。
    from contextlib import nullcontext

    def _store_lock():
        if gpu_lock is not None:
            return gpu_lock.acquire(owner="meguribi-daily", timeout=900)
        return nullcontext()

    if gpu_lock is None:
        _pr("[info] gpu_lock not found -> running without lock (be careful of GPU contention)")
    else:
        _pr(f"[info] per-store GPU lock enabled (free VRAM now: {gpu_lock.gpu_free_mb()} MiB)")

    total = len(slugs)
    gen_ok = gen_fail = wrote = write_err = 0
    for i, slug in enumerate(slugs, 1):
        _pr(f"[run {i}/{total}] generating daily report for slug={slug} (acquiring GPU lock) ...")
        # GPU を使う生成だけロック内。書き込み(ネットワーク)はロック外で行い、GPU を早く手放す。
        # ロック取得タイムアウト等の例外は、その店だけ失敗にして継続（バッチ全体を落とさない）。
        try:
            with _store_lock():
                record = build_record(
                    slug=slug,
                    store_row=store_map[slug],
                    edition=args.edition,
                    target_date=target_date,
                )
        except Exception as exc:  # noqa: BLE001
            _pr(f"      [lock/gen ERROR] {slug}: {exc}")
            record = _failure_record(slug, store_map[slug], args.edition, target_date, f"lock/gen error: {exc}")
        if record["is_published"]:
            gen_ok += 1
        else:
            gen_fail += 1
        _pr(f"      -> gen {'OK' if record['is_published'] else 'FAIL(' + str(record['error_message']) + ')'}")

        if args.mode == "dry-run":
            _print_record(slug, record)
            continue

        # 生成直後に即 upsert（バッチが途中で止まっても、そこまでの分は保存済み＝中断に強い／
        # Supabase で進捗が見える）。shadow は常に is_published=False で書く。
        if args.mode == "shadow":
            record["is_published"] = False
        try:
            _upsert_daily_report_to_supabase(record)
            wrote += 1
            _pr(f"      [write] upserted facts_id={record['facts_id']} is_published={record['is_published']}")
        except Exception as exc:  # noqa: BLE001
            write_err += 1
            _pr(f"      [write][ERROR] upsert failed for {slug}: {exc}")

    _pr(
        f"\n[summary] mode={args.mode} stores={total} generated_ok={gen_ok} "
        f"generated_fail={gen_fail} written={wrote} write_errors={write_err}"
    )
    if args.mode == "dry-run":
        _pr("[info] mode=dry-run -> NOTHING was written to Supabase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
