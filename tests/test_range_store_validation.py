"""/api/range の店舗slug厳格化 (bug #5) と limit 上限の既定値変更 (bug #6) のテスト。

2026-07 Fable audit バッチB4で追加。

bug #5: resolve_store_identifier() の「未知slug -> default_id にフォールバック」という
    寛容な挙動を /api/range にそのまま使っていたため、閉店済み(sapporo_ag)や存在しない
    (nagoya) slug を渡しても 422/404 にならず、default 店舗(長崎)の実データを ok:true で
    返してしまっていた。/api/range_multi は SLUG_TO_ID の既知slugのみ許可しているため
    422 になっており、単体/複数系で挙動が非対称だった。
    FIX: resolve_store_id_strict()（oriental/routes/common.py）が未知/閉店slugに対して
    None を返し、/api/range はそれを 404 {"ok": false, "error": "unknown-store"} にする。
    /api/forecast_* や /api/second_venues は寛容な resolve_store_id() のままなので対象外。

bug #6: 無認証で叩ける /api/range の limit 上限(MAX_RANGE_LIMIT)の既定値が 50000 だったため、
    1リクエストで巨大な応答を強制生成できる OOM レバーになっていた。既定を 6000 に下げた
    （env MAX_RANGE_LIMIT で上書き可能なのは維持）。クランプ処理自体
    （oriental/routes/data_range.py::_parse_range_query）は元々存在しており、今回は
    デフォルト値のみの変更。
"""

from __future__ import annotations

from oriental import create_app
from oriental.config import AppConfig
from oriental.routes.data_range import _parse_range_query
from oriental.utils.stores import ALL_STORE_IDS, SLUG_TO_ID


# ---------- bug #5: 未知/閉店slugの厳格化 ----------


def test_unknown_store_slug_returns_404():
    """存在しない slug（例: "nagoya" — 実際は nagoya_ag/nagoya_nishiki/nagoya_sakae のみ）
    は 404 + unknown-store を返す（以前は default 店舗の実データを ok:true で返していた）。
    """
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?store=nagoya")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body == {"ok": False, "error": "unknown-store"}


def test_closed_store_sapporo_ag_returns_404():
    """閉店済み sapporo_ag（stores.json から既に削除済み）は 404 を返す。"""
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?store=sapporo_ag")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body == {"ok": False, "error": "unknown-store"}


def test_totally_bogus_store_slug_returns_404():
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?store=___does_not_exist___")
    assert resp.status_code == 404
    assert resp.get_json() == {"ok": False, "error": "unknown-store"}


def test_missing_store_param_still_falls_back_to_default():
    """store/store_id を一切指定しない場合は従来通り cfg.store_id にフォールバックし、
    404 にはならない（後方互換: 単一店舗運用や既存の手動スモークツールを壊さない）。
    """
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?limit=1")
    assert resp.status_code == 200


def test_all_42_valid_slugs_resolve_for_api_range():
    """既知の全42店舗 slug は 404 にならず、従来通り 200 で応答する（byte-identical 動作）。"""
    app = create_app()
    client = app.test_client()
    assert len(SLUG_TO_ID) == len(ALL_STORE_IDS) == 42, (
        f"店舗数が想定(42)と異なります: {len(SLUG_TO_ID)}"
    )
    for slug in SLUG_TO_ID:
        resp = client.get(f"/api/range?store={slug}&limit=1")
        assert resp.status_code == 200, f"slug={slug} が 200 を返しませんでした: {resp.get_json()}"
        body = resp.get_json()
        assert body.get("ok") is True, f"slug={slug} の ok フラグが false でした: {body}"


def test_all_42_valid_store_ids_resolve_for_api_range():
    """短縮slugだけでなく store_id そのもの(ol_*/ay_*)でも 200 で応答する。"""
    app = create_app()
    client = app.test_client()
    for store_id in ALL_STORE_IDS:
        resp = client.get(f"/api/range?store={store_id}&limit=1")
        assert resp.status_code == 200, f"store_id={store_id} が 200 を返しませんでした: {resp.get_json()}"


# ---------- bug #6: MAX_RANGE_LIMIT の既定値変更 + クランプ確認 ----------


def test_default_max_range_limit_is_6000(monkeypatch):
    monkeypatch.delenv("MAX_RANGE_LIMIT", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.max_range_limit == 6000


def test_max_range_limit_env_override_still_works(monkeypatch):
    monkeypatch.setenv("MAX_RANGE_LIMIT", "9999")
    try:
        cfg = AppConfig.from_env()
        assert cfg.max_range_limit == 9999
    finally:
        monkeypatch.delenv("MAX_RANGE_LIMIT", raising=False)


def test_range_limit_120000_clamps_to_6000(monkeypatch):
    monkeypatch.delenv("MAX_RANGE_LIMIT", raising=False)
    app = create_app()
    cfg = app.config["APP_CONFIG"]
    with app.test_request_context("/api/range?limit=120000"):
        query = _parse_range_query(cfg)
    assert query.limit == 6000


def test_range_limit_1200_unchanged(monkeypatch):
    monkeypatch.delenv("MAX_RANGE_LIMIT", raising=False)
    app = create_app()
    cfg = app.config["APP_CONFIG"]
    with app.test_request_context("/api/range?limit=1200"):
        query = _parse_range_query(cfg)
    assert query.limit == 1200


def test_range_limit_5000_unchanged(monkeypatch):
    monkeypatch.delenv("MAX_RANGE_LIMIT", raising=False)
    app = create_app()
    cfg = app.config["APP_CONFIG"]
    with app.test_request_context("/api/range?limit=5000"):
        query = _parse_range_query(cfg)
    assert query.limit == 5000


def test_range_limit_zero_still_clamps_to_one(monkeypatch):
    """既存挙動（limit=0 は 1 にクランプ）が今回の変更で壊れていないことの確認。"""
    monkeypatch.delenv("MAX_RANGE_LIMIT", raising=False)
    app = create_app()
    cfg = app.config["APP_CONFIG"]
    with app.test_request_context("/api/range?limit=0"):
        query = _parse_range_query(cfg)
    assert query.limit == 1


def test_api_range_120000_request_returns_200_not_error():
    """エンドポイント経由でも巨大 limit は拒否ではなくクランプで処理される（挙動は不変）。"""
    app = create_app()
    client = app.test_client()
    resp = client.get("/api/range?limit=120000")
    assert resp.status_code == 200
