# app/multi_collect.py
# 38店舗ぶんの店内人数をスクレイピングして GAS(doPost) に投げるスクリプト

import os
import time
import re
import requests
from bs4 import BeautifulSoup

# .env から GAS_URL を読む（既存の doPost テストと同じ）
GAS_URL = os.environ["GAS_URL"]

# 店舗を回す間隔（秒）
BETWEEN_STORES_SEC = float(os.environ.get("BETWEEN_STORES_SEC", "1.0"))

# GAS への POST リトライ回数
GAS_MAX_RETRY = int(os.environ.get("GAS_MAX_RETRY", "3"))

# 38店舗分の store 名（GAS の STORE_MAP と一致させる）と各店舗 URL
STORES = [
    # 九州・沖縄・韓国
    {"store": "長崎",     "url": "https://oriental-lounge.com/stores/38"},
    {"store": "福岡",     "url": "https://oriental-lounge.com/stores/15"},
    {"store": "小倉",     "url": "https://oriental-lounge.com/stores/16"},
    {"store": "大分",     "url": "https://oriental-lounge.com/stores/40"},
    {"store": "熊本",     "url": "https://oriental-lounge.com/stores/22"},
    {"store": "宮崎",     "url": "https://oriental-lounge.com/stores/18"},
    {"store": "鹿児島",   "url": "https://oriental-lounge.com/stores/19"},
    {"store": "ag沖縄",   "url": "https://oriental-lounge.com/stores/20"},
    {"store": "ソウル カンナム", "url": "https://oriental-lounge.com/stores/34"},

    # 北海道・東北
    {"store": "ag札幌",   "url": "https://oriental-lounge.com/stores/1"},
    {"store": "ag仙台",   "url": "https://oriental-lounge.com/stores/2"},

    # 関東
    {"store": "渋谷本店", "url": "https://oriental-lounge.com/stores/4"},
    {"store": "恵比寿",   "url": "https://oriental-lounge.com/stores/35"},
    {"store": "ag渋谷",   "url": "https://oriental-lounge.com/stores/27"},
    {"store": "新宿",     "url": "https://oriental-lounge.com/stores/3"},
    {"store": "上野",     "url": "https://oriental-lounge.com/stores/33"},
    {"store": "ag上野",   "url": "https://oriental-lounge.com/stores/28"},
    {"store": "柏",       "url": "https://oriental-lounge.com/stores/42"},
    {"store": "町田",     "url": "https://oriental-lounge.com/stores/6"},
    {"store": "横浜",     "url": "https://oriental-lounge.com/stores/23"},
    {"store": "大宮",     "url": "https://oriental-lounge.com/stores/24"},
    {"store": "宇都宮",   "url": "https://oriental-lounge.com/stores/26"},
    {"store": "高崎",     "url": "https://oriental-lounge.com/stores/37"},

    # 中部
    {"store": "ag名古屋", "url": "https://oriental-lounge.com/stores/32"},
    {"store": "名古屋 錦", "url": "https://oriental-lounge.com/stores/25"},
    {"store": "名古屋 栄", "url": "https://oriental-lounge.com/stores/8"},
    {"store": "静岡",     "url": "https://oriental-lounge.com/stores/7"},
    {"store": "浜松",     "url": "https://oriental-lounge.com/stores/31"},
    {"store": "ag金沢",   "url": "https://oriental-lounge.com/stores/36"},

    # 関西・中国
    {"store": "大阪駅前", "url": "https://oriental-lounge.com/stores/41"},
    {"store": "ag梅田",   "url": "https://oriental-lounge.com/stores/10"},
    {"store": "天満",     "url": "https://oriental-lounge.com/stores/39"},
    {"store": "心斎橋",   "url": "https://oriental-lounge.com/stores/11"},
    {"store": "難波",     "url": "https://oriental-lounge.com/stores/12"},
    {"store": "京都",     "url": "https://oriental-lounge.com/stores/9"},
    {"store": "神戸",     "url": "https://oriental-lounge.com/stores/13"},
    {"store": "岡山",     "url": "https://oriental-lounge.com/stores/29"},
    {"store": "ag広島",   "url": "https://oriental-lounge.com/stores/14"},
]


# ========= GAS への POST（リトライ付き） =========

def post_to_gas(body: dict) -> None:
    """
    GAS_URL に JSON POST する。429 のときはリトライ。
    """
    for attempt in range(1, GAS_MAX_RETRY + 1):
        try:
            r = requests.post(GAS_URL, json=body, timeout=15)
            if r.status_code == 429 and attempt < GAS_MAX_RETRY:
                wait = 2 * attempt
                print(f"[warn] GAS 429 retry={attempt} wait={wait}s")
                time.sleep(wait)
                continue

            print(f"[post] store={body.get('store')} status={r.status_code} body={r.text}")
            return
        except Exception as e:
            print(f"[error] post_to_gas failed attempt={attempt} store={body.get('store')} err={e}")
            if attempt < GAS_MAX_RETRY:
                time.sleep(2 * attempt)
            else:
                return


# ========= スクレイピング =========

def _extract_count(soup: BeautifulSoup, patterns: list[str], selectors: list[str]) -> int | None:
    text = soup.get_text(" ", strip=True)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        match = re.search(r"\d+", node.get_text(strip=True).replace(",", ""))
        if match:
            return int(match.group())
    return None


def scrape_store(url: str) -> tuple[int | None, int | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        )
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    patterns_men = [r"男性\s*(\d+)", r"男性来店者数\s*(\d+)", r"男性.*?(\d+)"]
    selectors_men = [".male .count", ".male-count", ".js-men-count"]

    patterns_women = [r"女性\s*(\d+)", r"女性来店者数\s*(\d+)", r"女性.*?(\d+)"]
    selectors_women = [".female .count", ".female-count", ".js-women-count"]

    men = _extract_count(soup, patterns_men, selectors_men)
    women = _extract_count(soup, patterns_women, selectors_women)

    print(f"[scrape] url={url} men={men} women={women}")
    return men, women


# ========= 38店舗ぶんを一気に集めてリストで返す =========

def collect_all_once() -> list[dict]:
    results: list[dict] = []

    for entry in STORES:
        store_name = entry["store"]
        url = entry["url"]

        try:
            men, women = scrape_store(url)
        except Exception as e:
            print(f"[error] scrape failed store={store_name} url={url} err={e}")
            results.append({
                "store": store_name,
                "men": None,
                "women": None,
                "posted": False,
                "reason": "scrape-error",
            })
            continue

        if men is None or women is None:
            print(f"[warn] count missing store={store_name}")
            results.append({
                "store": store_name,
                "men": None,
                "women": None,
                "posted": False,
                "reason": "count-missing",
            })
            continue

        # GAS に投げる
        body = {"store": store_name, "men": int(men), "women": int(women)}
        post_to_gas(body)

        results.append({
            "store": store_name,
            "men": int(men),
            "women": int(women),
            "posted": True,
        })

        time.sleep(BETWEEN_STORES_SEC)

    return results


if __name__ == "__main__":
    collect_all_once()
