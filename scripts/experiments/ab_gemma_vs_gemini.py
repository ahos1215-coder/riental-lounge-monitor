#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gemma4:12b(ローカル) vs gemini-2.5-flash(API) の直接A/B比較。

同一の facts / system / prompt を両モデルに与え、週次(実質daily)と比較記事を生成して
横並び保存する。文章能力の“実物”比較用。GEMINI_API_KEY は .env.local から読み、値は出さない。
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, "scripts/experiments")
import local_llm_spike as spk  # SYSTEM, prompt_weekly, prompt_compare, fetch_store_facts, run_ollama, gpu_lock

OUT = Path("local_llm_spike_out")
GEMMA = "gemma4:12b"
GEMINI = "gemini-2.5-flash"


def load_gemini_key() -> str | None:
    for c in (".env.local", ".env", "frontend/.env.local"):
        p = Path(c)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'\s*GEMINI_API_KEY\s*=\s*(\S+)', line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return None


def gen_gemini(key: str, system: str, user: str) -> tuple[str, float, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI}:generateContent?key={key}"
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.7},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
        cand = (d.get("candidates") or [{}])[0]
        parts = ((cand.get("content") or {}).get("parts") or [])
        text = "".join(p.get("text", "") for p in parts)
        return text, time.time() - t0, ""
    except urllib.error.HTTPError as e:  # type: ignore
        try:
            body_err = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body_err = ""
        return "", time.time() - t0, f"HTTP {e.code}: {body_err}"
    except Exception as e:  # noqa: BLE001
        return "", time.time() - t0, str(e)


def main() -> int:
    key = load_gemini_key()
    if not key:
        print("[ERROR] GEMINI_API_KEY が見つかりません")
        return 1
    OUT.mkdir(exist_ok=True)

    # facts を一度だけ取得（両モデルに同一入力）。店名は日本語の正式名で渡す（固有名詞の崩れ回避）。
    fa = spk.fetch_store_facts("shibuya")
    fb = spk.fetch_store_facts("shinjuku")
    a_label = "オリエンタルラウンジ 渋谷店"
    b_label = "オリエンタルラウンジ 新宿店"
    print(f"[info] facts: shibuya={fa.get('source')} shinjuku={fb.get('source')}")

    tasks = [
        ("weekly", spk.prompt_weekly(a_label, fa)),
        ("compare", spk.prompt_compare(a_label, fa, b_label, fb)),
    ]

    results = []
    # --- Gemini (API, GPUロック不要) ---
    for task_name, user in tasks:
        print(f"[gemini] {task_name} ...")
        text, el, err = gen_gemini(key, spk.SYSTEM, user)
        out = OUT / f"AB_{task_name}__gemini-2.5-flash.md"
        out.write_text(f"<!-- model={GEMINI} task={task_name} elapsed={el:.1f}s chars={len(text)} err={err or 'none'} -->\n\n" + (text or f"(fail: {err})"), encoding="utf-8")
        print(f"   -> {out.name}  {el:.1f}s  {len(text)}字  {'OK' if text else 'FAIL '+err[:60]}")
        results.append((GEMINI, task_name, round(el, 1), len(text), "OK" if text else "FAIL"))

    # --- gemma4:12b (ローカル, GPUロックで音楽と排他) ---
    lock = spk.gpu_lock.acquire(owner="meguribi-ab", timeout=900) if spk.gpu_lock else nullcontext()
    with lock:
        for task_name, user in tasks:
            print(f"[gemma4:12b] {task_name} ... (ロード込み)")
            text, el, err = spk.run_ollama(GEMMA, spk.SYSTEM, user)
            out = OUT / f"AB_{task_name}__gemma4-12b.md"
            out.write_text(f"<!-- model={GEMMA} task={task_name} elapsed={el:.1f}s chars={len(text)} err={err or 'none'} -->\n\n" + (text or f"(fail: {err})"), encoding="utf-8")
            print(f"   -> {out.name}  {el:.1f}s  {len(text)}字  {'OK' if text else 'FAIL '+err[:60]}")
            results.append((GEMMA, task_name, round(el, 1), len(text), "OK" if text else "FAIL"))

    print("\n==== A/B SUMMARY ====")
    for m, t, s, c, st in results:
        print(f"{m:<20}{t:<10}{s:>7}s{c:>7}字  {st}")
    print(f"\n出力: {OUT.resolve()} の AB_*.md を読み比べ。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
