"""オリエンタルラウンジのスクレイピングが「解凍できない圧縮方式」「言語リダイレクト」で
静かに全店 (None, None) にならないことを固定する（2026-10-29〜 の全37店欠測の再発防止）。

事件の要点（実測で再現済み）:
  - Accept-Encoding に br を含めると oriental-lounge.com は Brotli で返す。requests は brotli
    ライブラリが無いと解凍できず resp.text が文字化けのバイナリになる（Render の requirements.txt
    に brotli は無い）→ セレクタも正規表現も当たらず、全店が静かに (None, None) になった。
  - Accept-Language に en を含めると /en/ へ 302 し、トップの店舗カード href が /en/stores/N になる。
ネットワークには一切出ない（requests.get を差し替える）。
"""

from __future__ import annotations

import pytest

import multi_collect as mc


class _FakeResp:
    def __init__(self, text: str, headers: dict[str, str] | None = None, content: bytes | None = None):
        self.text = text
        self.headers = headers or {}
        self.content = content if content is not None else text.encode("utf-8", "replace")
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def _two_stores() -> list[dict]:
    return list(mc.STORES[:2])


def _page_id(store: dict) -> int:
    import re

    return int(re.search(r"/stores/(\d+)", store["url"]).group(1))


def _top_html(stores: list[dict], prefix: str = "") -> str:
    cards = "".join(
        f'<a href="{prefix}/stores/{_page_id(s)}"><span>{i + 3} GENTLEMEN</span><span>{i + 5} LADIES</span></a>'
        for i, s in enumerate(stores)
    )
    return f"<!DOCTYPE html><html><body>{cards}</body></html>"


def _store_html(men: int = 4, women: int = 6) -> str:
    return (
        "<!DOCTYPE html><html><body>"
        "<section aria-label='現在の来客者数'>"
        f"<span class='customers-num num-male'>{men}</span>"
        f"<span class='customers-num num-female'>{women}</span>"
        "</section></body></html>"
    )


GARBLED_BR = "\x15A�\x00��u��|" * 40  # br を解凍できなかったときの resp.text の見え方


def test_ヘッダにbrを含めず日本語だけを要求する(monkeypatch):
    seen: list[dict] = []

    def fake_get(url, headers=None, **kw):
        seen.append(dict(headers or {}))
        if url.rstrip("/").endswith("oriental-lounge.com"):
            return _FakeResp(_top_html(_two_stores()))
        return _FakeResp(_store_html())

    monkeypatch.setattr(mc.requests, "get", fake_get)

    assert mc._scrape_top_page(_two_stores()) is not None
    assert mc._scrape_store_once(_two_stores()[0]["url"]) == (4, 6)

    assert len(seen) == 2
    for h in seen:
        enc = h["Accept-Encoding"].lower()
        assert "br" not in [t.strip() for t in enc.split(",")], enc
        assert "zstd" not in enc
        assert h["Accept-Language"] == "ja"  # en を含めると /en/ へ 302 される


def test_店舗ページが解凍できないとき原因を名指しして例外にする(monkeypatch):
    def fake_get(url, headers=None, **kw):
        return _FakeResp(GARBLED_BR, headers={"Content-Encoding": "br"}, content=b"\x15A\xb1\x00" * 100)

    monkeypatch.setattr(mc.requests, "get", fake_get)

    with pytest.raises(ValueError) as ei:
        mc._scrape_store_once(_two_stores()[0]["url"])
    assert "content-encoding=br" in str(ei.value)


def test_トップページが解凍できないときはNoneで個別取得へ落ちる(monkeypatch):
    def fake_get(url, headers=None, **kw):
        return _FakeResp(GARBLED_BR, headers={"Content-Encoding": "br"})

    monkeypatch.setattr(mc.requests, "get", fake_get)
    assert mc._scrape_top_page(_two_stores()) is None


@pytest.mark.parametrize("prefix", ["", "/en", "/ko"])
def test_トップページは言語プレフィックス付きのリンクも拾う(monkeypatch, prefix):
    stores = _two_stores()
    monkeypatch.setattr(mc.requests, "get", lambda url, headers=None, **kw: _FakeResp(_top_html(stores, prefix)))
    result = mc._scrape_top_page(stores)
    assert result is not None
    assert result[stores[0]["store_id"]] == (3, 5)
    assert result[stores[1]["store_id"]] == (4, 6)
