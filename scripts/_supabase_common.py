"""Supabase 設定読み込みの共有ヘルパー（config 読み込みのみ。REST/Storage の
fetch/retry/paging ロジックはスクリプトごとに挙動が異なるため統合しない）。

scripts/generate_weekly_insights.py と scripts/local_report_job.py に verbatim で
コピペされていた `_supabase_conf`（SUPABASE_URL / SERVICE_ROLE_KEY の環境変数解決）を
一本化する。

`_load_env`（.env / .env.local の手動パーサ）は元々 scripts/local_report_job.py と
scripts/backup_logs.py にあり、ここでは local_report_job.py の呼び出し元だけを
置き換える（backup_logs.py は今回のリファクタ対象外なので触らない）。
generate_weekly_insights.py は呼び出し元の scripts/run_weekly_local.ps1 が事前に
.env.local を読んで環境変数に流し込む前提で、自分では .env を読まない設計だった。
この非対称性は挙動を変えないためにそのまま維持し、generate_weekly_insights.py から
`_load_env` は呼び出さない。

トップレベルスクリプトとして `python scripts/x.py` 実行される前提（パッケージ化しない）
なので、他の scripts/ 内モジュール（例: commentary_quality_gate.py）と同じ規約で、
呼び出し側が `sys.path.insert(0, <自分のディレクトリ>)` した上で
`from _supabase_common import ...` のようにベアインポートする。
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    """.env / .env.local を読み込み os.environ に setdefault する。

    実環境変数（GitHub Actions secrets 等）が最優先。
    scripts/local_report_job.py（旧 `_load_env`）/ scripts/backup_logs.py の
    `_load_env` と同一の手動パーサ。
    """
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
    """SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY（フォールバック: SUPABASE_SERVICE_KEY）
    を解決する。どちらか欠けていれば None。

    scripts/generate_weekly_insights.py と scripts/local_report_job.py の
    旧 `_supabase_conf` と同一の探索順（キー自体は返り値以外に出力しない）。
    """
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )
    if not base or not key:
        return None
    return base, key
