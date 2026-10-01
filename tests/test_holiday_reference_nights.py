"""「先週の同じ夜」を手本にする2か所が、祝日がらみの夜とデータの無い夜を飛ばすことの番犬（2026-09-29）。

事故:
  シルバーウィーク（2026-09-19〜23）の翌週、予測が全店で普段の数倍に膨らんだ。予測は
    (1) 機械学習の特徴 same_dow_last_week_total（先週の同じ曜日・同じ時刻の人数）と
    (2) 後処理のブレンド（先週の同じ曜日・同じ時刻の実測を約4割混ぜる）
  の2か所で「7日前の夜」を手本にしており、9/21（敬老の日の夜、普段の約5倍の人出）などを
  普段の夜として使っていた。福岡の 9/28 夜は実測平均 7.5人に対し、予測の誤差が平均約70人。

修正後の契約（night_type.reference_offsets が単一の規則）:
  - 手本の候補は 7/14/21/28日前。祝日の夜・祝前夜・特別な夜（連休・年末年始・クリスマス等）は飛ばす。
  - 候補を近い順に見て、実測がある最初の夜を使う（収集停止などでデータが無い夜も飛ばす）。
    データの有無まで見るのは、手本なし（NaN）が「停止直後のシルバーウィークの夜」に偏っていて、
    モデルが「手本なし＝大混雑」と覚えていたため。
  - 全部だめなら手本なし（特徴は NaN、ブレンドはしない）。
  - 推論時、手本が通常の履歴（8日分）より古い週だけ、その夜を追加で取得する。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from oriental.ml import night_type
from oriental.ml.forecast_service import ForecastService
from oriental.ml.postprocess import blend_with_baseline
from oriental.ml.preprocess import prepare_dataframe

TZ = "Asia/Tokyo"
JST = timezone(timedelta(hours=9))


class Test祝日がらみの夜:
    @pytest.mark.parametrize(
        "night",
        [
            date(2026, 9, 18),  # 金曜・5連休の前夜
            date(2026, 9, 20),  # 連休中の日曜
            date(2026, 9, 21),  # 敬老の日（翌日も休み）
            date(2026, 9, 22),  # 国民の休日（翌日も祝日）
            date(2026, 9, 23),  # 秋分の日の夜
            date(2026, 7, 19),  # 3連休（海の日 7/20）の前夜＝翌日が祝日
            date(2026, 12, 24),  # クリスマスイブ
        ],
    )
    def test_手本にしない(self, night: date) -> None:
        assert night_type.is_holiday_influenced_night(night)

    @pytest.mark.parametrize(
        "night",
        [
            date(2026, 9, 28),  # 普段の月曜
            date(2026, 6, 12),  # 普段の金曜（ただの週末前夜は普段どおり比べる）
            date(2026, 6, 13),  # 普段の土曜
            date(2026, 6, 14),  # 普段の日曜
        ],
    )
    def test_手本にする(self, night: date) -> None:
        assert not night_type.is_holiday_influenced_night(night)

    def test_普段の週は7日前から順に全部使える(self) -> None:
        assert night_type.reference_offsets(date(2026, 6, 10)) == (7, 14, 21, 28)

    @pytest.mark.parametrize("night", [date(2026, 9, 27), date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)])
    def test_シルバーウィークの翌週は7日前を飛ばす(self, night: date) -> None:
        assert night_type.reference_offsets(night) == (14, 21, 28)


def _hist(rows: list[tuple[str, int, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"ts": pd.Timestamp(ts, tz=TZ), "men": m, "women": w, "total": m + w} for ts, m, w in rows]
    )


def _pt(ts: str, men: float, women: float) -> dict:
    return {
        "ts": pd.Timestamp(ts, tz=TZ).isoformat(),
        "men_pred": float(men),
        "women_pred": float(women),
        "total_pred": float(men + women),
    }


class Testブレンド:
    def test_先週が祝日なら2週前を手本にする(self) -> None:
        hist = _hist([("2026-09-21 23:00", 100, 100), ("2026-09-14 23:00", 5, 5)])
        out, n = blend_with_baseline([_pt("2026-09-28 23:00", 40, 40)], hist, TZ, w_ml=0.0)
        assert n == 1
        assert out[0]["total_pred"] == pytest.approx(10.0)  # 9/14 の実測（9/21 の 200 ではない）

    def test_データの無い夜も飛ばす(self) -> None:
        hist = _hist([("2026-09-21 23:00", 100, 100), ("2026-09-07 23:00", 6, 6)])  # 9/14 は欠測
        out, n = blend_with_baseline([_pt("2026-09-28 23:00", 40, 40)], hist, TZ, w_ml=0.0)
        assert n == 1
        assert out[0]["total_pred"] == pytest.approx(12.0)  # 21日前

    def test_手本が無ければブレンドしない(self) -> None:
        hist = _hist([("2026-09-21 23:00", 100, 100)])
        out, n = blend_with_baseline([_pt("2026-09-28 23:00", 40, 40)], hist, TZ, w_ml=0.2)
        assert n == 0
        assert out[0]["total_pred"] == pytest.approx(80.0)  # ML のまま

    def test_普段の週は従来どおり7日前(self) -> None:
        hist = _hist([("2026-06-03 23:00", 7, 7), ("2026-05-27 23:00", 1, 1)])
        out, n = blend_with_baseline([_pt("2026-06-10 23:00", 40, 40)], hist, TZ, w_ml=0.0)
        assert n == 1
        assert out[0]["total_pred"] == pytest.approx(14.0)


def _rec(ts: str, total: int, store_id: str = "ol_fukuoka") -> dict:
    return {
        "ts": datetime.fromisoformat(ts).replace(tzinfo=JST).isoformat(),
        "men": total // 2,
        "women": total - total // 2,
        "total": total,
        "store_id": store_id,
        "weather_code": 1,
        "temp_c": 20.0,
        "precip_mm": 0.0,
    }


def _feature_at(df: pd.DataFrame, ts: str) -> float:
    row = df.loc[df["ts"] == pd.Timestamp(ts, tz=TZ)]
    assert len(row) == 1
    return float(row["same_dow_last_week_total"].iloc[0])


class Test機械学習の特徴:
    def test_先週が祝日なら2週前の人数(self) -> None:
        df = prepare_dataframe(
            [_rec("2026-09-14T23:00", 20), _rec("2026-09-21T23:00", 200), _rec("2026-09-28T23:00", 10)], TZ
        )
        assert _feature_at(df, "2026-09-28 23:00") == pytest.approx(20.0)

    def test_データの無い夜は飛ばして次の候補(self) -> None:
        df = prepare_dataframe(
            [_rec("2026-08-31T23:00", 15), _rec("2026-09-21T23:00", 200), _rec("2026-09-28T23:00", 10)], TZ
        )
        assert _feature_at(df, "2026-09-28 23:00") == pytest.approx(15.0)  # 28日前

    def test_候補が全部無くても祝日の夜は使わない(self) -> None:
        """手本なしの行は後段（prepare_dataframe 末尾）で表の中央値に埋められる。ここでは全行が
        手本なしなので 0。少なくとも 9/21（祝日の夜）の 200 を拾ってはいけない。"""
        df = prepare_dataframe([_rec("2026-09-21T23:00", 200), _rec("2026-09-28T23:00", 10)], TZ)
        assert _feature_at(df, "2026-09-28 23:00") == pytest.approx(0.0)

    def test_普段の週は7日前(self) -> None:
        df = prepare_dataframe(
            [_rec("2026-05-27T23:00", 5), _rec("2026-06-03T23:00", 30), _rec("2026-06-10T23:00", 10)], TZ
        )
        assert _feature_at(df, "2026-06-10 23:00") == pytest.approx(30.0)

    def test_深夜0時台は前夜として扱う(self) -> None:
        """9/29 01:00 は 9/28 の夜。手本は 9/15 01:00（=9/14 の夜）であって 9/22 01:00 ではない。"""
        df = prepare_dataframe(
            [_rec("2026-09-15T01:00", 20), _rec("2026-09-22T01:00", 200), _rec("2026-09-29T01:00", 10)], TZ
        )
        assert _feature_at(df, "2026-09-29 01:00") == pytest.approx(20.0)

    def test_店ごとに引く(self) -> None:
        df = prepare_dataframe(
            [
                _rec("2026-09-14T23:00", 20, "ol_fukuoka"),
                _rec("2026-09-14T23:00", 90, "ol_shibuya"),
                _rec("2026-09-28T23:00", 10, "ol_fukuoka"),
                _rec("2026-09-28T23:00", 50, "ol_shibuya"),
            ],
            TZ,
        )
        got = df.loc[df["ts"] == pd.Timestamp("2026-09-28 23:00", tz=TZ)].set_index("store_id")["same_dow_last_week_total"]
        assert got["ol_fukuoka"] == pytest.approx(20.0)
        assert got["ol_shibuya"] == pytest.approx(90.0)


class _FakeProvider:
    def __init__(self, results: dict[date, object]) -> None:
        self.logger = logging.getLogger("test")
        self.results = results
        self.calls: list[date] = []

    def fetch_range(self, *, store_id, limit, start_ts=None, end_ts=None):
        night = start_ts.astimezone(JST).date()
        self.calls.append(night)
        result = self.results.get(night, [])
        if isinstance(result, BaseException):
            raise result
        return result


def _service(provider: _FakeProvider) -> ForecastService:
    return ForecastService(provider, TZ, history_days=8)


def _tonight(night: date) -> pd.DatetimeIndex:
    start = pd.Timestamp(night.year, night.month, night.day, 19, tz=TZ)
    return pd.date_range(start=start, periods=40, freq="15min")


class Test推論時の追加取得:
    def test_欠測の夜を飛ばして実測のある夜で止まる(self) -> None:
        provider = _FakeProvider({date(2026, 9, 7): [_rec("2026-09-07T23:00", 12)]})
        extra = _service(provider)._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        # 9/21 は祝日なので取りに行かない。9/14 は空 → 9/7 で見つかって止まる（8/31 は取らない）
        assert provider.calls == [date(2026, 9, 14), date(2026, 9, 7)]
        assert len(extra) == 1

    def test_履歴にある夜は取りに行かない(self) -> None:
        provider = _FakeProvider({})
        history = _hist([("2026-09-14 23:00", 5, 5)])
        assert _service(provider)._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), history) == []
        assert provider.calls == []

    def test_取得に失敗しても例外を出さない(self) -> None:
        provider = _FakeProvider({date(2026, 9, 14): RuntimeError("down")})
        assert _service(provider)._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([])) == []

    def test_2回目は覚えた結果を使い取りに行かない(self) -> None:
        """2026-09-30 夜は予測キャッシュが切れるたびに同じ過去の夜を取り直し、推定 約3,800回の
        余分な Supabase リクエストになっていた。実測なし（空）の夜も覚える。"""
        provider = _FakeProvider({date(2026, 9, 7): [_rec("2026-09-07T23:00", 12)]})
        svc = _service(provider)
        first = svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        second = svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        assert provider.calls == [date(2026, 9, 14), date(2026, 9, 7)]  # 2回目はゼロ回
        assert first == second and len(second) == 1

    def test_店が違えば別に取りに行く(self) -> None:
        provider = _FakeProvider({date(2026, 9, 14): [_rec("2026-09-14T23:00", 12)]})
        svc = _service(provider)
        svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        svc._fetch_reference_nights("ol_shibuya", _tonight(date(2026, 9, 28)), _hist([]))
        assert provider.calls == [date(2026, 9, 14), date(2026, 9, 14)]

    def test_取得に失敗した結果は覚えない(self) -> None:
        provider = _FakeProvider({date(2026, 9, 14): RuntimeError("down")})
        svc = _service(provider)
        svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        provider.results[date(2026, 9, 14)] = [_rec("2026-09-14T23:00", 12)]
        extra = svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        assert provider.calls == [date(2026, 9, 14), date(2026, 9, 14)]
        assert len(extra) == 1

    def test_期限0なら覚えない(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORECAST_REFERENCE_NIGHT_CACHE_TTL", "0")
        provider = _FakeProvider({date(2026, 9, 14): [_rec("2026-09-14T23:00", 12)]})
        svc = _service(provider)
        svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        svc._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([]))
        assert provider.calls == [date(2026, 9, 14), date(2026, 9, 14)]

    def test_fetch_rangeの無い提供元では何もしない(self) -> None:
        class _Legacy:
            logger = logging.getLogger("test")

        assert ForecastService(_Legacy(), TZ)._fetch_reference_nights("ol_fukuoka", _tonight(date(2026, 9, 28)), _hist([])) == []
