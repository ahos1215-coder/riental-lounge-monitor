"""train_ml_model.py の「まとめ・既定モデル選択」ブロックの番犬（B-15）。

main() 全体（実学習・Supabase Storage へのアップロードを伴う）は動かさない方針は
tests/test_train_ml_model_retention_wiring.py と同じ。ここでは main() から切り出した
純関数に合成の dict を渡し、インライン時代と同じ値を返すことだけを固定する。
"""

from __future__ import annotations

import scripts.train_ml_model as tm


class Testゲート判定のまとめ:
    def test_3種類の判定を数える(self) -> None:
        decisions = [
            {"store_id": "a", "decision": "replaced"},
            {"store_id": "b", "decision": "skipped"},
            {"store_id": "c", "decision": "carried_forward"},
            {"store_id": "d", "decision": "replaced"},
        ]
        assert tm._summarize_gate_decisions(decisions) == {
            "replaced": 2,
            "skipped": 1,
            "carried_forward": 1,
        }

    def test_空でも3キーが0で揃う(self) -> None:
        assert tm._summarize_gate_decisions([]) == {
            "replaced": 0,
            "skipped": 0,
            "carried_forward": 0,
        }


class Test既定店舗の選択:
    def test_指定店舗が今回学習されていればそれを使う(self) -> None:
        assert tm._pick_default_store("ol_shibuya", {"ol_shibuya", "ol_ueno"}) == "ol_shibuya"

    def test_指定店舗が今回学習されていなければ辞書順の先頭(self) -> None:
        assert tm._pick_default_store("ol_kobe", {"ol_ueno", "ol_shibuya"}) == "ol_shibuya"

    def test_店舗指定が無ければ辞書順の先頭(self) -> None:
        assert tm._pick_default_store(None, {"ol_ueno", "ol_shibuya"}) == "ol_shibuya"

    def test_今回1店も学習していなければNone(self) -> None:
        """既存のグローバル model_men.txt/model_women.txt を触らせないための分岐。"""
        assert tm._pick_default_store("ol_shibuya", set()) is None
