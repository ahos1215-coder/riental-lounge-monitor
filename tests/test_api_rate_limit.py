"""番犬: 公開 /api/* の IP 単位レート制限とリクエスト行数上限（外部レビュー F4）。

背景: Render 上の Flask には認証もレート制限も無く、Next.js プロキシ側の制限は
公開 Render URL を直接叩くだけで迂回できた（`/api/range_multi` は 42店 × 6000行 ×
12並列を1リクエストで要求でき、workers=1 / threads=8 の本番を飽和させられる）。

ここで固定するのは次の4点:
  1. `/api/*` は IP 単位で 1分あたり N 回に制限される（超過は 429 + ok:false）
  2. `/healthz` `/readyz` `/tasks/*` は**制限の対象外**（監視と cron を落とさない）
  3. env `API_RATE_LIMIT_ENABLED=0` で丸ごと無効化できる（緊急停止スイッチ）
  4. `/api/range_multi` は 店舗数 × limit が予算を超えると 422 で弾く

このファイルのテストは外部ネットワークに一切出ない（Supabase 資格情報をダミーにするか
空にして、実データ取得の手前で判定が出るところだけを見る）。
"""

from __future__ import annotations

import pytest

from oriental import create_app
from oriental.config import AppConfig
from oriental.routes.common import InProcessRateLimiter, is_rate_limited_path


def _no_supabase(monkeypatch) -> None:
    """Supabase 資格情報を空にする（/healthz などが外へ出ないようにする）。"""
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "")


def _dummy_supabase(monkeypatch) -> None:
    """provider が None にならない程度のダミー設定（実際の取得までは行かせない）。"""
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "dummy-key-for-tests")


# ---------- 1. カウンタ本体 ----------


def test_固定窓カウンタは上限を超えた分だけ拒否する():
    limiter = InProcessRateLimiter(limit_per_min=3)
    assert [limiter.check("1.2.3.4", now=100.0)[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.check("1.2.3.4", now=100.0)
    assert allowed is False
    assert retry_after >= 1


def test_別IPは互いのカウンタに影響しない():
    limiter = InProcessRateLimiter(limit_per_min=2)
    limiter.check("1.1.1.1", now=0.0)
    limiter.check("1.1.1.1", now=0.0)
    assert limiter.check("1.1.1.1", now=0.0)[0] is False
    assert limiter.check("2.2.2.2", now=0.0)[0] is True


def test_窓が明けたらカウンタは復帰する():
    limiter = InProcessRateLimiter(limit_per_min=1)
    assert limiter.check("9.9.9.9", now=0.0)[0] is True
    assert limiter.check("9.9.9.9", now=30.0)[0] is False
    assert limiter.check("9.9.9.9", now=61.0)[0] is True


def test_追跡IP数は上限を超えて増え続けない():
    limiter = InProcessRateLimiter(limit_per_min=100, max_tracked_ips=16)
    for i in range(200):
        limiter.check(f"10.0.0.{i}", now=float(i))
    # 内部辞書を直接覗く（メモリ暴走が無いことの回帰ガード）
    assert len(limiter._buckets) <= 16  # noqa: SLF001


# ---------- 2. 対象パスの選別 ----------


@pytest.mark.parametrize(
    "path,limited",
    [
        ("/api/range", True),
        ("/api/range_multi", True),
        ("/api/forecast_today", True),
        ("/api/megribi_score", True),
        # 監視と cron は絶対に落とさない
        ("/healthz", False),
        ("/readyz", False),
        ("/tasks/multi_collect", False),
        ("/tasks/multi_collect/status", False),
        ("/api/tasks/collect_all_once", False),
        ("/static/x.png", False),
        ("/", False),
    ],
)
def test_レート制限の対象パス(path, limited):
    assert is_rate_limited_path(path) is limited


# ---------- 3. Flask への配線 ----------


def test_api_は上限超過で429とok_falseを返す(monkeypatch):
    _no_supabase(monkeypatch)
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("API_RATE_LIMIT_PER_MIN", "3")
    client = create_app(AppConfig.from_env()).test_client()

    for _ in range(3):
        assert client.get("/api/meta").status_code == 200

    resp = client.get("/api/meta")
    assert resp.status_code == 429
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "rate-limited"
    assert int(resp.headers["Retry-After"]) >= 1


def test_healthzとtasksは制限を受けない(monkeypatch):
    _no_supabase(monkeypatch)
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("API_RATE_LIMIT_PER_MIN", "2")
    client = create_app(AppConfig.from_env()).test_client()

    for _ in range(10):
        assert client.get("/healthz").status_code == 200
    # /tasks/* は CRON_SECRET 認証で 401/403 になり得るが、429 にはならない
    for _ in range(10):
        assert client.get("/tasks/multi_collect/status").status_code != 429


def test_XForwardedForは末尾IPごとに数える_先頭は詐称できるので使わない(monkeypatch):
    _no_supabase(monkeypatch)
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("API_RATE_LIMIT_PER_MIN", "2")
    client = create_app(AppConfig.from_env()).test_client()

    for _ in range(2):
        assert client.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.1, 10.0.0.1"}).status_code == 200
    # 同じ「最後の要素(=Renderが見た接続元)」なら、先頭を書き換えても同じバケット。
    # 先頭を信用していた頃は、ここで先頭を変えるだけで制限を素通りできていた。
    assert client.get("/api/meta", headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}).status_code == 429
    # 別クライアントは巻き込まれない
    assert client.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.2"}).status_code == 200


def test_キルスイッチで完全に無効化できる(monkeypatch):
    _no_supabase(monkeypatch)
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("API_RATE_LIMIT_PER_MIN", "2")
    app = create_app(AppConfig.from_env())
    assert app.config.get("API_RATE_LIMITER") is None
    client = app.test_client()
    for _ in range(20):
        assert client.get("/api/meta").status_code == 200


# ---------- 4. 1リクエストあたりの総行数上限 ----------


def test_range_multi_は総行数の予算超過を422で弾く(monkeypatch):
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "0")  # ここでは行数上限だけを見る
    _dummy_supabase(monkeypatch)
    monkeypatch.setenv("MAX_RANGE_TOTAL_ROWS", "600")
    client = create_app(AppConfig.from_env()).test_client()

    resp = client.get("/api/range_multi?stores=shibuya,shinjuku,ueno&limit=6000")
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "range-request-too-large"
    # 42店 × MAX_RANGE_LIMIT のフルスケール攻撃も同じ入口で止まる
    assert client.get("/api/range_multi?stores=shibuya&limit=6000").status_code == 422


def test_攻撃的な組み合わせは既定値でも予算超過になる(monkeypatch):
    monkeypatch.delenv("MAX_RANGE_TOTAL_ROWS", raising=False)
    cfg = AppConfig.from_env()
    # 外部レビューが指摘した「42店 × 6000行」は既定予算を大幅に超える
    assert 42 * cfg.max_range_limit > cfg.max_range_total_rows


def test_正規の呼び出しは既定の予算に収まる(monkeypatch):
    """実際に使われている最大の組み合わせが予算内であること（誤爆防止の番犬）。

    - /stores 一覧 & 関連店舗カード: 12店 × STORE_CARD_RANGE_LIMIT(48)
    - /compare:                      3店(MAX_COMPARE) × 200
    - warm_cdn_local.py の単体 range: 1店 × 1200（昨日ビュー）
    """
    monkeypatch.delenv("MAX_RANGE_TOTAL_ROWS", raising=False)
    cfg = AppConfig.from_env()
    for stores, limit in ((12, 48), (3, 200), (1, 1200), (42, 48)):
        assert stores * limit <= cfg.max_range_total_rows, (stores, limit)


def test_行数予算はenvで上書きできる(monkeypatch):
    monkeypatch.setenv("MAX_RANGE_TOTAL_ROWS", "777")
    assert AppConfig.from_env().max_range_total_rows == 777


# --------------------------------------------------------------------------- #
# client_ip(): 本番(Render + Cloudflare)で「効かない」事故を踏まえた優先順の固定
# --------------------------------------------------------------------------- #
def test_CFConnectingIPが最優先で使われる(monkeypatch):
    """Cloudflare が必ず自分で上書きするヘッダなので、詐称された XFF より優先する。"""
    from oriental.routes.common import client_ip

    app = create_app(AppConfig.from_env())
    with app.test_request_context(
        "/api/meta",
        headers={
            "CF-Connecting-IP": "203.0.113.5",
            "X-Forwarded-For": "9.9.9.9, 10.0.0.1",
        },
    ):
        assert client_ip() == "203.0.113.5"


def test_CFヘッダが無ければXFFの末尾を使う(monkeypatch):
    """先頭は接続元が自由に詐称できるので使わない（それだと制限を素通りできる）。"""
    from oriental.routes.common import client_ip

    app = create_app(AppConfig.from_env())
    with app.test_request_context(
        "/api/meta", headers={"X-Forwarded-For": "9.9.9.9, 198.51.100.2"}
    ):
        assert client_ip() == "198.51.100.2"


def test_ヘッダが何も無ければremote_addr(monkeypatch):
    from oriental.routes.common import client_ip

    app = create_app(AppConfig.from_env())
    with app.test_request_context("/api/meta", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert client_ip() == "127.0.0.1"


def test_healthzにレート制限の観測値が出る(monkeypatch):
    """本番で「効いているのか」を外から切り分けられるようにするための計器。"""
    client = create_app(AppConfig.from_env()).test_client()
    body = client.get("/healthz").get_json()
    assert body["api_rate_limit"]["enabled"] is True
    assert body["api_rate_limit"]["per_min"] >= 1
    assert "tracked_keys" in body["api_rate_limit"]

    client.get("/api/meta", headers={"CF-Connecting-IP": "203.0.113.77"})
    client.get("/api/meta", headers={"CF-Connecting-IP": "203.0.113.77"})
    status = client.get("/healthz").get_json()["api_rate_limit"]
    # 同じ CF-Connecting-IP は1バケットにまとまる（増え続けるならキーが壊れている）
    assert status["max_count_in_window"] >= 2
