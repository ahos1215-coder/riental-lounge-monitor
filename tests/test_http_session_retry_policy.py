"""共有 HTTP セッションの再試行ポリシーが第三者に上書きされないことの回帰テスト。

背景（2026-08-18 の全停止 → 2026-08-19 の再発防止）:
oriental/clients/http.py の ConfiguredSession は「500 はリトライしない」ポリシーを
持つ。Supabase の statement timeout(57014) は HTTP 500 で返るが、これは待てば直る
一時障害ではなく何度投げても必ず失敗する恒久エラーで、リトライすると 1 リクエストに
つき 4 回 × timeout 12s ≒ 50 秒スレッドを占有し、受け口を埋め尽くしてサービス全体を
停止させた。

ところが SupabaseLogsProvider / SecondVenuesRepository / GooglePlacesClient の
__init__ が「渡された session」に対しても status_forcelist=(429,500,502,503,504) の
HTTPAdapter を mount() し直していたため、Flask の共有 ConfiguredSession
(app.config["HTTP_SESSION"]) が最初のプロバイダ生成時に上書きされ、上の修正が
アプリ全体で無効化されていた。

本テストは「実物の ConfiguredSession を渡すと adapter が一切差し替えられない」ことを
固定する。テスト用のフェイクセッション（mount が no-op）ではこの回帰を検出できない
ため、必ず実物のセッションで検証すること。
"""

from __future__ import annotations

import pytest
import requests

from oriental.clients.google_places import GooglePlacesClient
from oriental.clients.http import ConfiguredSession
from oriental.data.provider import SupabaseLogsProvider
from oriental.data.second_venues_repository import SecondVenuesRepository


def _make_shared_session() -> ConfiguredSession:
    return ConfiguredSession(timeout=12.0, retries=3, user_agent="test-agent")


def _forcelists(session: requests.Session) -> list[tuple]:
    return [
        tuple(session.adapters[scheme].max_retries.status_forcelist)
        for scheme in ("http://", "https://")
    ]


def _build_all(session):
    """3クラスすべてを同じ session で生成する（本番の生成順を模す）。"""
    return [
        SupabaseLogsProvider(
            base_url="https://example.supabase.co", api_key="k", session=session
        ),
        SecondVenuesRepository(
            base_url="https://example.supabase.co", api_key="k", session=session
        ),
        GooglePlacesClient(api_key="k", session=session),
    ]


def test_shared_session_keeps_500_out_of_forcelist():
    """共有 ConfiguredSession を渡しても 500 が再試行対象に戻らないこと。"""
    session = _make_shared_session()
    before = _forcelists(session)
    assert all(500 not in fl for fl in before), "前提: ConfiguredSession は 500 を再試行しない"

    _build_all(session)

    for forcelist in _forcelists(session):
        assert 500 not in forcelist, "共有セッションの forcelist に 500 が復活している"
    assert _forcelists(session) == before


def test_shared_session_adapters_are_not_replaced():
    """渡された session の adapter オブジェクト自体が差し替えられないこと
    （forcelist が同値でも mount し直せば呼び出し側の他の設定を失う）。"""
    session = _make_shared_session()
    original = {scheme: session.adapters[scheme] for scheme in ("http://", "https://")}

    clients = _build_all(session)

    for scheme, adapter in original.items():
        assert session.adapters[scheme] is adapter, f"{scheme} の adapter が差し替えられた"
    # 各クラスは渡されたセッションをそのまま保持する
    for client in clients:
        assert client.session is session


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SupabaseLogsProvider(base_url="https://example.supabase.co", api_key="k"),
        lambda: SecondVenuesRepository(base_url="https://example.supabase.co", api_key="k"),
        lambda: GooglePlacesClient(api_key="k"),
    ],
    ids=["supabase_provider", "second_venues_repo", "google_places"],
)
def test_fallback_session_retries_without_500(factory):
    """session 未指定の fallback は自前 Session に再試行を付けるが、
    その forcelist にも 500 を含めない。"""
    client = factory()
    assert isinstance(client.session, requests.Session)
    for forcelist in _forcelists(client.session):
        assert 500 not in forcelist
        assert 429 in forcelist
        assert 503 in forcelist
