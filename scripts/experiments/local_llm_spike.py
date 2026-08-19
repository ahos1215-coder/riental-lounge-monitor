#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ローカルLLM 品質スパイク（go/no-go 用）

目的:
  Gemini API を置き換えるローカルLLM候補を、実データで「週次レポート」と
  「渋谷 vs 新宿 比較記事」の2タスクについて生成させ、横並びで目視比較する。

使い方（このファイルがあるリポジトリのルートで）:
  1) Ollama を入れて、モデルを pull しておく（初回のみ・別途手順参照）:
       ollama pull qwen3.5:4b
       ollama pull qwen3.5:9b
       ollama pull gemma4:12b
  2) 実行:
       python scripts/experiments/local_llm_spike.py
  3) 生成物は ./local_llm_spike_out/ に .md で保存される。エディタで読み比べる。

設計メモ:
  - 各モデルは keep_alive:0 で「生成後すぐアンロード」→ VRAM を次モデル/音楽PJに明け渡す
    （8GB共有・衝突させない運用に合わせる。3モデルを積み上げない）。
  - 実データはライブ backend から取得。取れなければ埋め込みサンプルにフォールバック
    （＝Ollama さえ動けばオフラインでも品質の当たりは見られる）。
  - 小型モデルに JSON 厳格出力は強制しない（フォーマット税回避）。本文＋見出しの質を見る。
"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path

# Ollama 呼び出し・facts 取得・SYSTEM プロンプトの実体は scripts/_ollama_common.py にある
# （本番の日次/週次ジョブと共有する正本）。このファイルは実験（モデル横並び比較）専用。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _ollama_common import (  # noqa: E402,F401  (再エクスポート: ab_gemma_vs_gemini.py 等が spk.* 経由で使う)
    BACKEND,
    FACTS_FETCH_RETRIES,
    FACTS_FETCH_TIMEOUT_SEC,
    MODEL,
    NUM_CTX,
    OLLAMA_URL,
    SYSTEM,
    TIMEOUT_SEC,
    _get_json,
    _pct,
    check_backend_health,
    check_ollama,
    facts_block,
    fetch_store_facts,
    run_ollama,
    unload_ollama,
)

# 共有GPUロック（音楽PJと衝突しないための排他）。見つからなければロック無しで続行。
try:
    sys.path.insert(0, r"C:\Users\Public\共有データ系")
    import gpu_lock  # type: ignore
except Exception:  # noqa: BLE001
    gpu_lock = None

# ---- 実験の設定（ここを編集すれば対象モデル/店舗を変えられる） --------------
OLLAMA = OLLAMA_URL  # 後方互換の別名
MODELS = ["qwen3.5:4b", "qwen3.5:9b", "gemma4:12b"]  # 質重視なら qwen3.5:4b-q8_0 等に差し替え可
STORE_A = "shibuya"   # 週次レポート対象 & 比較の片方
STORE_B = "shinjuku"  # 比較のもう片方
OUT_DIR = Path("local_llm_spike_out")

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def prompt_weekly(store_label: str, facts: dict) -> str:
    return (
        f"次のデータは相席ラウンジ「{store_label}」の直近の混雑状況です。\n\n"
        f"{facts_block(facts, store_label)}\n\n"
        "これをもとに、今週の混雑傾向と『いつ行くと良さそうか』を、"
        "来店検討者向けに150〜250字程度でまとめた短い週次レポートを書いてください。"
        "見出し(#)から始め、数字に基づく具体的な示唆を1つ入れてください。"
    )


def prompt_compare(a_label: str, fa: dict, b_label: str, fb: dict) -> str:
    return (
        f"次は相席ラウンジ2店舗の混雑データです。\n\n"
        f"{facts_block(fa, a_label)}\n\n{facts_block(fb, b_label)}\n\n"
        f"この2店舗「{a_label}」と「{b_label}」の違いを、データに基づいて比較する"
        "ブログ記事(400〜600字)を書いてください。見出し(#)＋小見出し(##)を使い、"
        "『どちらがどんな人・シーンに向くか』の結論を必ず入れてください。数字を具体的に引用し、"
        "分からない点は断定しないこと。"
    )


def main() -> int:
    installed = check_ollama()
    if installed is None or installed == []:
        # 空でも接続自体は成功しているかもしれないので区別
        try:
            _get_json(f"{OLLAMA}/api/tags", timeout=5)
        except Exception:
            print("[ERROR] Ollama に接続できません (http://localhost:11434)。")
            print("        Ollama を起動してください。未インストールなら手順参照。")
            return 1
    print(f"[info] Ollama 稼働中。pull 済みモデル: {installed or '(なし)'}")

    OUT_DIR.mkdir(exist_ok=True)
    print(f"[info] 出力先: {OUT_DIR.resolve()}")

    print(f"[info] 実データ取得中: {STORE_A}, {STORE_B} ...")
    fa = fetch_store_facts(STORE_A)
    fb = fetch_store_facts(STORE_B)
    a_label = f"オリエンタルラウンジ {STORE_A}"
    b_label = f"オリエンタルラウンジ {STORE_B}"
    print(f"[info] {STORE_A} facts source={fa.get('source')} / {STORE_B} facts source={fb.get('source')}")

    tasks = [
        ("weekly", prompt_weekly(a_label, fa)),
        ("compare", prompt_compare(a_label, fa, b_label, fb)),
    ]

    # 共有GPUを掴む間は排他ロック（音楽PJと衝突させない）。gpu_lock が無ければ素通り。
    if gpu_lock is not None:
        print(f"[info] GPUロック取得中 (free VRAM: {gpu_lock.gpu_free_mb()} MiB) ...")
        lock_cm = gpu_lock.acquire(owner="meguribi-spike", timeout=900)
    else:
        print("[info] gpu_lock 未検出 → ロック無しで実行（衝突に注意）")
        lock_cm = nullcontext()

    summary = []
    with lock_cm:
        for model in MODELS:
            if installed and not any(model.split(":")[0] in m for m in installed):
                print(f"[warn] {model} が pull されていない可能性。`ollama pull {model}` を先に。スキップせず試行します。")
            for task_name, user in tasks:
                print(f"\n[run] model={model} task={task_name} ... 生成中(初回はモデルロードで時間がかかる)")
                text, elapsed, err = run_ollama(model, SYSTEM, user)
                safe_model = model.replace(":", "_").replace("/", "_")
                out = OUT_DIR / f"{task_name}__{safe_model}.md"
                header = f"<!-- model={model} task={task_name} elapsed={elapsed:.1f}s chars={len(text)} error={err or 'none'} -->\n\n"
                out.write_text(header + (text if text else f"(生成失敗: {err})"), encoding="utf-8")
                status = "OK" if text and not err else f"FAIL({err[:60]})"
                print(f"     -> {out.name}  {elapsed:.1f}s  {len(text)}字  {status}")
                summary.append((model, task_name, round(elapsed, 1), len(text), status))

    print("\n==== SUMMARY ====")
    print(f"{'model':<16}{'task':<10}{'sec':>7}{'chars':>8}  status")
    for m, t, s, c, st in summary:
        print(f"{m:<16}{t:<10}{s:>7}{c:>8}  {st}")
    print(f"\n読み比べ: {OUT_DIR.resolve()} の .md を開いて、日本語の自然さ/正確さ/構成を比較してください。")
    print("同じ task 同士（例 compare__*.md）を横並びで見るのがおすすめ。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
