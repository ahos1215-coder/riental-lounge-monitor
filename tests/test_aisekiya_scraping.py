"""相席屋スクレイピングのテスト。

ネットワークアクセスは行わず、HTML パース・容量計算・パーセント変換ロジックのみ検証する。
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from multi_collect import (
    AISEKIYA_STORES,
    _aisekiya_capacity,
    _scrape_aisekiya,
)


SAMPLE_HTML = """
<html><body>
<ul>
  <li class="p-congestionList__item">
    <a class="p-storeCard" href="https://aiseki-ya.com/shop/shibuya2/">
      <div class="p-storeCard__header">渋谷店</div>
      <div class="p-storeCard__body">
        <dl class="c-storeData">
          <dt class="c-storeData__term--men">Men</dt>
          <dd class="c-storeData__description">
            <span class="c-storeData__now">25</span><span class="c-storeData__unit">%</span>
          </dd>
        </dl>
        <dl class="c-storeData">
          <dt class="c-storeData__term--women">Women</dt>
          <dd class="c-storeData__description">
            <span class="c-storeData__now">35</span><span class="c-storeData__unit">%</span>
          </dd>
        </dl>
      </div>
    </a>
  </li>
  <li class="p-congestionList__item">
    <a class="p-storeCard" href="https://aiseki-ya.com/shop/ueno/">
      <div class="p-storeCard__header">上野店</div>
      <div class="p-storeCard__body">
        <dl class="c-storeData">
          <dt class="c-storeData__term--men">Men</dt>
          <dd class="c-storeData__description">
            <span class="c-storeData__now">100</span><span class="c-storeData__unit">%</span>
          </dd>
        </dl>
        <dl class="c-storeData">
          <dt class="c-storeData__term--women">Women</dt>
          <dd class="c-storeData__description">
            <span class="c-storeData__now">0</span><span class="c-storeData__unit">%</span>
          </dd>
        </dl>
      </div>
    </a>
  </li>
</ul>
</body></html>
"""


def test_aisekiya_stores_master_data():
    """マスタデータが期待される 6 店舗を含むこと"""
    expected_slugs = {"shibuya2", "ikebukurohigashiguchi", "ueno", "chibachuo", "yokonishi", "nigatabandai"}
    assert set(AISEKIYA_STORES.keys()) == expected_slugs

    # 全店舗に必須キーが含まれること
    for slug, info in AISEKIYA_STORES.items():
        assert "name" in info
        assert "store_id" in info
        assert info["store_id"].startswith("ay_")
        assert info["tables"] > 0
        assert info["vip"] >= 0


def test_aisekiya_capacity_formula():
    """容量計算: (テーブル数 + VIP数) × 2 = 性別ごとの最大収容枠"""
    # 渋谷: 16卓 + VIP3 = 19 × 2 = 38
    assert _aisekiya_capacity("shibuya2") == 38
    # 上野: 14卓 + VIP1 = 15 × 2 = 30
    assert _aisekiya_capacity("ueno") == 30
    # 千葉: 19卓 + VIP3 = 22 × 2 = 44
    assert _aisekiya_capacity("chibachuo") == 44
    # 横浜: 10卓 + VIP7 = 17 × 2 = 34
    assert _aisekiya_capacity("yokonishi") == 34
    # 新潟: 13卓 + VIP2 = 15 × 2 = 30
    assert _aisekiya_capacity("nigatabandai") == 30
    # 池袋: 11卓 + VIP3 = 14 × 2 = 28
    assert _aisekiya_capacity("ikebukurohigashiguchi") == 28


def test_aisekiya_capacity_unknown_slug():
    """存在しない slug の場合は 0 を返す"""
    assert _aisekiya_capacity("unknown_slug") == 0


def test_aisekiya_html_parsing_men_women_extraction():
    """サンプル HTML から男女パーセンテージが正しく抽出できること"""
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    cards = soup.select("li.p-congestionList__item")
    assert len(cards) == 2

    # 1 件目: 渋谷店
    card = cards[0]
    href = card.select_one("a.p-storeCard").get("href")
    assert "shibuya2" in href
    men_node = card.select_one("dt.c-storeData__term--men")
    men_dd = men_node.find_next_sibling("dd")
    men_pct = int(men_dd.select_one("span.c-storeData__now").get_text(strip=True))
    assert men_pct == 25

    women_node = card.select_one("dt.c-storeData__term--women")
    women_dd = women_node.find_next_sibling("dd")
    women_pct = int(women_dd.select_one("span.c-storeData__now").get_text(strip=True))
    assert women_pct == 35


def test_aisekiya_percentage_to_count_conversion():
    """パーセント → 推定人数の逆算ロジック"""
    # 渋谷店 capacity=38、25% → round(38 * 0.25) = round(9.5) = 10
    capacity = _aisekiya_capacity("shibuya2")
    assert round(capacity * 25 / 100) == 10
    assert round(capacity * 35 / 100) == 13

    # 上野店 capacity=30、100% → 30
    capacity_ueno = _aisekiya_capacity("ueno")
    assert round(capacity_ueno * 100 / 100) == 30
    assert round(capacity_ueno * 0 / 100) == 0


def test_aisekiya_slug_extraction_regex():
    """href から slug を抽出する正規表現の動作確認"""
    pattern = r"/shop/([^/]+)/?"
    cases = [
        ("https://aiseki-ya.com/shop/shibuya2/", "shibuya2"),
        ("https://aiseki-ya.com/shop/ueno/", "ueno"),
        ("https://aiseki-ya.com/shop/ikebukurohigashiguchi/", "ikebukurohigashiguchi"),
        ("/shop/chibachuo/", "chibachuo"),
    ]
    for url, expected in cases:
        m = re.search(pattern, url)
        assert m is not None, f"Pattern failed for {url}"
        assert m.group(1) == expected


@patch("multi_collect.requests.get")
def test_scrape_aisekiya_success_with_mocked_html(mock_get):
    """モック HTML を返してスクレイピング全体の動作を検証"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    results = _scrape_aisekiya()

    # 渋谷店と上野店が結果に含まれること
    assert "ay_shibuya" in results
    assert "ay_ueno" in results

    # 渋谷店: men 25% × 38 = 10, women 35% × 38 = 13
    men, women = results["ay_shibuya"]
    assert men == 10
    assert women == 13

    # 上野店: men 100% × 30 = 30, women 0% × 30 = 0
    men, women = results["ay_ueno"]
    assert men == 30
    assert women == 0


@patch("multi_collect.requests.get")
def test_scrape_aisekiya_handles_network_error(mock_get):
    """ネットワークエラー時は空 dict を返してフォールバック"""
    mock_get.side_effect = Exception("network down")
    results = _scrape_aisekiya()
    assert results == {}
