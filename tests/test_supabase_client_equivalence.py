"""番犬: oriental/clients/supabase.py の共通ヘルパーが、集約前に各所へ手書きされて
いたヘッダ辞書・URL 文字列と完全に同じものを作ることを固定する。

ここが崩れると Supabase が 401 を返す（apikey / Authorization の片方が欠ける）か、
Storage の URL が二重スラッシュで 400 になる。集約の前後で「文字列として同じ」で
あることだけを見る（リトライ方針・例外方針は各呼び出し元の責務なので触れない）。
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from oriental.clients.supabase import auth_headers, storage_get_bytes, storage_object_url


KEY = "service-role-key"


def test_認証ヘッダが旧リテラルと一致する():
    assert auth_headers(KEY) == {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
    }


def test_認証ヘッダにAcceptを足した形が旧リテラルと一致する():
    # provider.py / second_venues_repository.py / health.py が使っていた形
    assert auth_headers(KEY, accept_json=True) == {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Accept": "application/json",
    }


def test_認証ヘッダにContentTypeを足した形が旧リテラルと一致する():
    # second_venues_repository.upsert_many が使っていた形
    assert auth_headers(KEY, accept_json=True, content_type=True) == {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


@pytest.mark.parametrize(
    "base_url, bucket, path",
    [
        ("https://example.supabase.co", "ml-models", "accuracy/scores/summary.json"),
        ("https://example.supabase.co", "ml-models", "accuracy/blend_weights.json"),
        ("https://example.supabase.co", "ml-models", "forecast/latest/metadata.json"),
    ],
)
def test_StorageのURLが旧リテラルと一致する(base_url, bucket, path):
    assert storage_object_url(base_url, bucket, path) == (
        f"{base_url}/storage/v1/object/{bucket}/{path}"
    )


def test_StorageのURLは余分なスラッシュを潰す():
    assert (
        storage_object_url("https://example.supabase.co/", "/ml-models/", "/a/b.json")
        == "https://example.supabase.co/storage/v1/object/ml-models/a/b.json"
    )


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, body: bytes = b""):
    return urllib.error.HTTPError("https://example", code, "err", {}, None)


def test_StorageGETは本文をそのまま返す(monkeypatch):
    payload = {"weights": {"ol_shibuya": 0.4}}
    seen = {}

    def _fake_urlopen(req, timeout=10):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        seen["timeout"] = timeout
        return _FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    raw = storage_get_bytes("https://example.supabase.co", KEY, "ml-models", "a/b.json")
    assert json.loads(raw.decode()) == payload
    assert seen["url"] == "https://example.supabase.co/storage/v1/object/ml-models/a/b.json"
    # urllib は header 名を Capitalize して保持する
    assert seen["headers"]["Apikey"] == KEY
    assert seen["headers"]["Authorization"] == f"Bearer {KEY}"
    assert seen["timeout"] == 10


def test_StorageGETは404でNoneを返す(monkeypatch):
    def _fake_urlopen(req, timeout=10):
        raise _http_error(404)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    assert storage_get_bytes("https://example.supabase.co", KEY, "ml-models", "a.json") is None


def test_StorageGETは400のnot_foundでNoneを返す(monkeypatch):
    class _Err(urllib.error.HTTPError):
        def read(self):  # type: ignore[override]
            return b'{"error":"not_found"}'

    def _fake_urlopen(req, timeout=10):
        raise _Err("https://example", 400, "bad", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    assert storage_get_bytes("https://example.supabase.co", KEY, "ml-models", "a.json") is None


def test_StorageGETはその他のHTTPエラーを伝播する(monkeypatch):
    def _fake_urlopen(req, timeout=10):
        raise _http_error(500)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        storage_get_bytes("https://example.supabase.co", KEY, "ml-models", "a.json")
