"""収集の書き込みを「全店まとめて1回」にした変更（2026-09-26）の番犬。

背景:
  Supabase は HTTP リクエスト1回ごとに API ゲートウェイのログを1件残し、その量が無料プランの
  「ログ取り込み枠（月1GB、2027年初めから適用）」に数えられる。以前は 5分ごとの収集で42店を
  1店ずつ INSERT し（1日 5,040回）、毎時の天気の有無も1店ずつ問い合わせていた。

ここで固定する契約:
  - 1回の収集で Supabase への INSERT は（オリエンタル・相席屋それぞれ）1リクエストだけ。
  - 行の中身は以前の1行ずつの payload と同じ（天気が無ければキーごと省く）。
  - まとめ書きが HTTP エラーで拒否されたら、1行ずつ送り直す（1店の不正な値で全店を道連れにしない）。
  - 通信エラー・タイムアウトで結果が分からないときは、先に確かめ、入っていない行だけを送り直す。
    確かめられなければ送り直さない（二重登録を避ける）。
  - 天気の有無の問い合わせは全店まとめて1回。失敗しても収集は止めない（天気を取り直すだけ）。

ネットワークには出ない（requests を差し替える）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

import multi_collect as mc

TS = "2026-09-26T10:00:00.123456+00:00"


class _Resp:
    def __init__(self, status: int = 201, payload: object = None, text: str = "") -> None:
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class _Recorder:
    """requests.post / requests.get の呼び出しを記録し、用意した応答を順に返す。"""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.gets: list[dict] = []
        self.post_results: list[object] = []  # _Resp か、送出したい例外
        self.get_results: list[object] = []

    def post(self, url, json=None, headers=None, params=None, timeout=None):  # noqa: A002
        self.posts.append({"url": url, "json": json, "headers": headers or {}, "params": params})
        result = self.post_results.pop(0) if self.post_results else _Resp(201)
        if isinstance(result, BaseException):
            raise result
        return result

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append({"url": url, "params": params, "headers": headers or {}})
        result = self.get_results.pop(0) if self.get_results else _Resp(200, [])
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(mc, "HAS_SUPABASE", True)
    monkeypatch.setattr(mc, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(mc, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setattr(mc.requests, "post", rec.post)
    monkeypatch.setattr(mc.requests, "get", rec.get)
    return rec


def _row(store_id: str, *, weather: bool = False, ts: str = TS) -> dict[str, object]:
    if weather:
        return mc.build_supabase_log_row(store_id, 3, 4, 1, "晴れ", 21.5, 0.0, ts=ts)
    return mc.build_supabase_log_row(store_id, 3, 4, None, None, None, None, ts=ts)


class Test行の中身:
    def test_天気が無ければキーごと省く(self) -> None:
        assert _row("ol_shibuya") == {
            "store_id": "ol_shibuya",
            "ts": TS,
            "men": 3,
            "women": 4,
            "total": 7,
            "src_brand": "oriental",
        }

    def test_天気があれば4列を付ける(self) -> None:
        row = _row("ol_shibuya", weather=True)
        assert (row["weather_code"], row["weather_label"], row["temp_c"], row["precip_mm"]) == (1, "晴れ", 21.5, 0.0)

    def test_相席屋はブランドを付け替える(self) -> None:
        row = mc.build_supabase_log_row("ay_chiba", 1, 2, None, None, None, None, brand=mc.AISEKIYA_BRAND)
        assert row["src_brand"] == "aisekiya"

    def test_tsを渡さなければ今の時刻(self) -> None:
        row = mc.build_supabase_log_row("ol_shibuya", 1, 2, None, None, None, None)
        assert abs(datetime.fromisoformat(str(row["ts"])) - datetime.now(timezone.utc)) < timedelta(seconds=5)


class Testまとめ書き:
    def test_成功なら1リクエストで全行を送る(self, net: _Recorder) -> None:
        rows = [_row("ol_shibuya", weather=True), _row("ol_ebisu"), _row("ol_ueno")]
        assert mc.insert_supabase_logs(rows) == {"ol_shibuya": True, "ol_ebisu": True, "ol_ueno": True}
        (post,) = net.posts
        assert post["url"] == "https://example.supabase.co/rest/v1/logs"
        assert post["json"] == rows
        assert post["params"] == {"columns": ",".join(mc.LOGS_INSERT_COLUMNS)}
        # 天気の無い行も「列の既定値」で入る＝以前の「キーごと省く」と同じ結果
        assert "missing=default" in post["headers"]["Prefer"]
        assert "return=minimal" in post["headers"]["Prefer"]
        assert net.gets == []

    def test_送る列は行の全キーを覆う(self) -> None:
        assert set(_row("ol_shibuya", weather=True)) <= set(mc.LOGS_INSERT_COLUMNS)

    def test_HTTPエラーなら1行ずつ送り直す(self, net: _Recorder) -> None:
        rows = [_row("ol_shibuya"), _row("ol_ebisu"), _row("ol_ueno")]
        net.post_results = [_Resp(400, text="bad"), _Resp(201), _Resp(400, text="bad"), _Resp(201)]
        assert mc.insert_supabase_logs(rows) == {"ol_shibuya": True, "ol_ebisu": False, "ol_ueno": True}
        assert len(net.posts) == 4
        # 送り直しは1行ずつ（配列ではなく1つの行、columns 指定なし）
        assert [p["json"] for p in net.posts[1:]] == rows
        assert all(p["params"] is None for p in net.posts[1:])

    def test_タイムアウトなら確かめて入っていない行だけ送り直す(self, net: _Recorder) -> None:
        rows = [_row("ol_shibuya"), _row("ol_ebisu")]
        net.post_results = [requests.Timeout("slow"), _Resp(201)]
        # ol_shibuya は入っていた（Supabase は 'Z' でも '+00:00' でも返しうる）
        net.get_results = [_Resp(200, [{"store_id": "ol_shibuya", "ts": "2026-09-26T10:00:00.123456Z"}])]
        assert mc.insert_supabase_logs(rows) == {"ol_shibuya": True, "ol_ebisu": True}
        assert len(net.posts) == 2
        assert net.posts[1]["json"] == rows[1]
        (check,) = net.gets
        assert ("store_id", "in.(ol_ebisu,ol_shibuya)") in check["params"]

    def test_同じ店でもtsが違う行は入っていたと数えない(self, net: _Recorder) -> None:
        rows = [_row("ol_shibuya")]
        net.post_results = [requests.ConnectionError("reset"), _Resp(201)]
        net.get_results = [_Resp(200, [{"store_id": "ol_shibuya", "ts": "2026-09-26T09:55:00+00:00"}])]
        assert mc.insert_supabase_logs(rows) == {"ol_shibuya": True}
        assert len(net.posts) == 2

    def test_確かめられなければ送り直さない(self, net: _Recorder) -> None:
        rows = [_row("ol_shibuya"), _row("ol_ebisu")]
        net.post_results = [requests.Timeout("slow")]
        net.get_results = [requests.ConnectionError("down")]
        assert mc.insert_supabase_logs(rows) == {"ol_shibuya": False, "ol_ebisu": False}
        assert len(net.posts) == 1

    def test_確かめの応答がエラーでも送り直さない(self, net: _Recorder) -> None:
        net.post_results = [requests.Timeout("slow")]
        net.get_results = [_Resp(503)]
        assert mc.insert_supabase_logs([_row("ol_shibuya")]) == {"ol_shibuya": False}
        assert len(net.posts) == 1

    def test_空なら何も送らない(self, net: _Recorder) -> None:
        assert mc.insert_supabase_logs([]) == {}
        assert net.posts == [] and net.gets == []

    def test_Supabase未設定なら成功扱いで何も送らない(self, net: _Recorder, monkeypatch) -> None:
        monkeypatch.setattr(mc, "HAS_SUPABASE", False)
        assert mc.insert_supabase_logs([_row("ol_shibuya")]) == {"ol_shibuya": True}
        assert net.posts == []


class Test書き込みフェーズ:
    def test_オリエンタルは1回で送り件数を数える(self, net: _Recorder, monkeypatch) -> None:
        monkeypatch.setattr(mc, "post_to_gas", lambda body: None)
        stores = [
            {"store_id": "ol_shibuya", "store": "渋谷店"},
            {"store_id": "ol_ebisu", "store": "恵比寿店"},
            {"store_id": "ol_ueno", "store": "上野店"},
        ]
        scrape = {"ol_shibuya": (3, 4), "ol_ebisu": (None, None), "ol_ueno": (5, 6)}
        weather = {"ol_shibuya": (1, "晴れ", 21.5, 0.0)}

        assert mc._write_results(stores, scrape, weather) == (2, 1)
        (post,) = net.posts
        sent = post["json"]
        assert [r["store_id"] for r in sent] == ["ol_shibuya", "ol_ueno"]
        assert sent[0]["weather_code"] == 1 and "weather_code" not in sent[1]
        # 同じ回の行は同じ ts（送った後に ts で確かめられるように）
        assert sent[0]["ts"] == sent[1]["ts"]

    def test_一部の店だけ失敗しても件数が合う(self, net: _Recorder, monkeypatch) -> None:
        monkeypatch.setattr(mc, "post_to_gas", lambda body: None)
        stores = [{"store_id": "ol_shibuya", "store": "渋谷店"}, {"store_id": "ol_ebisu", "store": "恵比寿店"}]
        net.post_results = [_Resp(400), _Resp(201), _Resp(400)]
        assert mc._write_results(stores, {"ol_shibuya": (3, 4), "ol_ebisu": (1, 1)}, {}) == (1, 1)

    def test_相席屋も1回で送る(self, net: _Recorder) -> None:
        scrape = {info["store_id"]: (2, 3) for info in mc.AISEKIYA_STORES.values()}
        success, fail = mc._write_aisekiya_results(scrape, {})
        assert (success, fail) == (len(mc.AISEKIYA_STORES), 0)
        (post,) = net.posts
        assert {r["src_brand"] for r in post["json"]} == {"aisekiya"}
        assert len(post["json"]) == len(mc.AISEKIYA_STORES)


class Test天気の有無の問い合わせ:
    def test_全店まとめて1回で聞く(self, net: _Recorder) -> None:
        net.get_results = [_Resp(200, [{"store_id": "ol_shibuya"}, {"store_id": "ol_shibuya"}])]
        assert mc._stores_with_weather_this_hour(["ol_ueno", "ol_shibuya"]) == {"ol_shibuya"}
        (call,) = net.gets
        params = dict(call["params"])
        assert params["store_id"] == "in.(ol_shibuya,ol_ueno)"
        assert params["weather_code"] == "not.is.null"

    @pytest.mark.parametrize("failure", [requests.ConnectionError("down"), _Resp(500), _Resp(200, {"oops": 1})])
    def test_失敗しても空集合で収集は続く(self, net: _Recorder, failure) -> None:
        net.get_results = [failure]
        assert mc._stores_with_weather_this_hour(["ol_shibuya"]) == set()

    def test_プリフェッチは店の数に関係なく問い合わせ1回(self, net: _Recorder, monkeypatch) -> None:
        class _AtTopOfHour(datetime):
            @classmethod
            def now(cls, tz=None):  # 毎時の最初の10分（天気を取りに行く時間帯）に固定する
                return datetime(2026, 9, 26, 11, 2, tzinfo=timezone.utc).astimezone(tz) if tz else datetime(2026, 9, 26, 20, 2)

        monkeypatch.setattr(mc, "datetime", _AtTopOfHour)
        monkeypatch.setattr(mc, "ENABLE_WEATHER", True)
        fetched: list[tuple[float, float]] = []
        monkeypatch.setattr(mc, "fetch_current_weather", lambda lat, lon: fetched.append((lat, lon)) or (1, "晴れ", 20.0, 0.0))
        net.get_results = [_Resp(200, [{"store_id": mc.STORES[0]["store_id"]}])]

        weather = mc._prefetch_weather(mc.STORES)

        assert len(net.gets) == 1
        # もう天気がある店は取りに行かない／それ以外は天気が付く
        assert mc.STORES[0]["store_id"] not in weather
        assert all(w == (1, "晴れ", 20.0, 0.0) for w in weather.values())
        assert len(weather) == len({s["store_id"] for s in mc.STORES}) - 1
