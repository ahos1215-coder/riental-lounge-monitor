"""多店舗指定（?stores=slug1,slug2,...）の解釈が3エンドポイントで一致することの番犬。

背景（A-08）: /api/range_multi・/api/forecast_today_multi・/api/megribi_score は
それぞれ別々に slug をパースしており、順序が食い違っていた:

  - range_multi        : 既知フィルタ → 重複除去 → 上限
  - forecast_today_multi: 既知フィルタ → 上限（重複除去なし。同じ店を2回計算していた）
  - megribi_score      : 上限 → 既知フィルタ（不正 slug が上限ぶん並ぶと
                          末尾の正当な slug が丸ごと落ちていた）

utils/stores.parse_store_slugs() に一本化し、range_multi の順序（既知フィルタ →
重複除去 → 上限）へ揃えた。通常入力の結果は3者とも従来どおり不変で、変わるのは
「重複 slug」「不正 slug を上限ぶん並べた」異常入力のみ（下の CASES を参照）。
"""

from __future__ import annotations

import pytest

from oriental import create_app
from oriental.utils.stores import MAX_MULTI_STORES, SLUG_TO_ID, parse_store_slugs


# --- parse_store_slugs 単体 ---------------------------------------------------


def test_既知slugのみが店舗idつきで返る():
    assert parse_store_slugs("gangnam,ay_ueno") == [
        ("gangnam", "ol_gangnam"),
        ("ay_ueno", "ay_ueno"),
    ]


def test_空白と大文字は正規化される():
    assert parse_store_slugs(" GANGNAM , shibuya ") == [
        ("gangnam", "ol_gangnam"),
        ("shibuya", "ol_shibuya"),
    ]


def test_未知slugと空トークンは落ちる():
    assert parse_store_slugs("nope,,gangnam, ,ol_zzz") == [("gangnam", "ol_gangnam")]


def test_重複slugは1つに畳まれる():
    assert parse_store_slugs("gangnam,GANGNAM,gangnam,shibuya") == [
        ("gangnam", "ol_gangnam"),
        ("shibuya", "ol_shibuya"),
    ]


def test_上限は既知slugを数えてから適用される():
    """不正 slug を先に上限ぶん並べても、後ろの正当な slug は落ちない。"""
    raw = ",".join(f"zzz{i}" for i in range(MAX_MULTI_STORES)) + ",gangnam"
    assert parse_store_slugs(raw) == [("gangnam", "ol_gangnam")]


def test_上限は既知slugの件数で打ち切られる():
    assert parse_store_slugs("gangnam,shibuya,ay_ueno", max_stores=2) == [
        ("gangnam", "ol_gangnam"),
        ("shibuya", "ol_shibuya"),
    ]


def test_全店指定は42店舗そのまま通る():
    """既定の上限は全店舗数なので、全 slug を渡しても1件も落ちない。"""
    assert len(parse_store_slugs(list(SLUG_TO_ID.keys()))) == len(SLUG_TO_ID)


def test_リスト入力はカンマで分割されない():
    """?store=（単店指定）の値をそのまま渡す経路。カンマ入りは未知 slug 扱い。"""
    assert parse_store_slugs(["gangnam,shibuya"]) == []
    assert parse_store_slugs(None) == []


# --- 3エンドポイントの一致 ----------------------------------------------------


class _FakeProvider:
    """Supabase の代わり。どの店舗にも同じ1行を返す。"""

    def fetch_range(self, *, store_id, limit, start_ts=None, end_ts=None):
        return [{"ts": "2026-07-09T23:00:00+09:00", "men": 3, "women": 4, "total": 7}]


class _FakeForecastService:
    def forecast_today(self, *, store_id, freq_min, start_h, end_h):
        return {
            "ok": True,
            "data": [
                {
                    "ts": "2026-07-09T23:00:00+09:00",
                    "men_pred": 3.0,
                    "women_pred": 4.0,
                    "total_pred": 7.0,
                }
            ],
            "reasoning": {"signals": {}, "notes": []},
            "insufficient_history": False,
            "blend_w_ml": 0.2,
            "blended_slots": 1,
            "clamped_slots": 0,
        }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("DISABLE_MODEL_PRELOAD", "1")
    monkeypatch.setenv("ENABLE_FORECAST", "1")

    from oriental.routes import data_range as data_range_module
    from oriental.routes import forecast as forecast_module

    provider = _FakeProvider()
    monkeypatch.setattr(data_range_module, "_supabase_provider", lambda cfg: provider)
    monkeypatch.setattr(forecast_module, "_supabase_provider", lambda cfg: provider)
    monkeypatch.setattr(forecast_module, "_service", lambda: _FakeForecastService())

    return create_app().test_client()


_BOGUS = ",".join(f"zzz{i}" for i in range(MAX_MULTI_STORES))

CASES = [
    # (説明, stores=に渡す文字列, 期待する slug 集合)
    ("通常入力", "gangnam,shibuya,ay_ueno", {"gangnam", "shibuya", "ay_ueno"}),
    ("重複slug", "gangnam,gangnam,shibuya", {"gangnam", "shibuya"}),
    ("不正slug多数+末尾に正当slug", _BOGUS + ",gangnam", {"gangnam"}),
    ("大文字/空白混じり", "GANGNAM, shibuya ,nope", {"gangnam", "shibuya"}),
]


@pytest.mark.parametrize("label,stores,expected", CASES, ids=[c[0] for c in CASES])
def test_3エンドポイントのslug解釈が一致する(client, label, stores, expected):
    r_range = client.get(f"/api/range_multi?stores={stores}&limit=1")
    r_forecast = client.get(f"/api/forecast_today_multi?stores={stores}")
    r_score = client.get(f"/api/megribi_score?stores={stores}")

    assert r_range.status_code == 200
    assert r_forecast.status_code == 200
    assert r_score.status_code == 200

    range_slugs = set(r_range.get_json()["by_slug"].keys())
    forecast_slugs = set(r_forecast.get_json()["by_slug"].keys())
    score_items = r_score.get_json()["data"]
    score_slugs = [item["slug"] for item in score_items]

    assert range_slugs == expected
    assert forecast_slugs == expected
    # megribi_score は list なので、重複が混ざっていないことも合わせて確認する。
    assert sorted(score_slugs) == sorted(expected)


def test_megribi_scoreの店舗省略時は全店舗を返す(client):
    resp = client.get("/api/megribi_score")
    assert resp.status_code == 200
    slugs = [item["slug"] for item in resp.get_json()["data"]]
    assert set(slugs) == set(SLUG_TO_ID.keys())


def test_megribi_scoreの単店指定はカンマ区切りとして解釈されない(client):
    """?store= は1トークン扱い（従来挙動）。カンマ入りは未知 slug として空になる。"""
    single = client.get("/api/megribi_score?store=gangnam")
    assert [item["slug"] for item in single.get_json()["data"]] == ["gangnam"]

    commaed = client.get("/api/megribi_score?store=gangnam,shibuya")
    assert commaed.get_json()["data"] == []
