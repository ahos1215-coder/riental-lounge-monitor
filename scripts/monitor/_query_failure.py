#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""監視スクリプトが「照会に失敗した理由」を通知に載せるための共通部品。

なぜ必要か（2026-09-09 / Supabase egress 超過事故の反省）:
  2026-09-05 に Supabase が全リクエストへ HTTP 402（exceed_cached_egress_quota）を
  返し始めた。検知そのものは動いていて、収集ハートビートは停止の5時間後から
  16回連続で赤かった。壊れていたのは**届け方**である:
    - 監視スクリプトは照会に失敗すると detail を出す**前に** sys.exit(1) していた。
      その結果 GHA の `outputs.detail` が空になり、通知本文には何も載らなかった。
    - 残るのはワークフロー側の固定文だけで、そこに書かれた原因は
      「PC停止 / Render障害 / cron-job.org障害」の3つ。**全部ハズレ**だった。
      本当の原因（Supabaseが402）は一文字も通知に出ず、気づくまで3日半かかった。

  ここでは失敗の中身（HTTP ステータスとレスポンス本文の先頭）を必ず文章にして返し、
  401/402/403 を「課金・認証起因」として他の失敗（タイムアウト・通信断）と区別する。
  区別する理由は2つ:
    1) 通知に載せる推定原因が正反対になる（PC/Render/cron ではなく Supabase 側）。
    2) 再試行しても結果が変わらない。指数バックオフで何十秒も待つのは無駄なので、
       この3ステータスは即座に諦めて理由を報告する方が早く人間に届く。

失敗の分類は3つある（2026-09-09 に3つ目を追加）:
  1) 課金・認証起因（401/402/403）    … Supabase 側。再試行しても直らない。
  2) 通信失敗（ステータスが取れない） … タイムアウト・DNS・接続断。
  3) 本文が想定外（UnexpectedBody）  … **HTTP は成功している**が中身が想定した形ではない。
     3つ目を分けた理由: 以前は 2) と一緒くたに QueryFailed へ包んでいたため、通知に
     「HTTP ステータス: （なし＝通信失敗・タイムアウト）」と出ていた。実際は通信できて
     いて本文だけがおかしいので、読んだ人がネットワークを疑って調べる先を間違える。

公開リポジトリであることの扱い:
  detail_lines(include_body=False) は「誰でも読める場所（GITHUB_STEP_SUMMARY / Actions の
  ログ）に出す版」で、レスポンス本文200字を落とす。本文はプロジェクト内部の情報を含み
  うるので、非公開の通知（LINE / Slack）にだけ載せる。

トップレベルスクリプトとして `python scripts/monitor/x.py` 実行される前提なので、
scripts/_retry_common.py 等と同じ規約で、呼び出し側が
`sys.path.insert(0, <自分のディレクトリ>)` した上でベアインポートする。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 「課金・認証起因」として他の失敗と区別するステータス。
#   401 = キー不正 / 403 = 権限不足・プロジェクト停止 / 402 = 支払い・クォータ超過
# いずれも再試行で直らないし、原因の説明文が通常の障害とまったく違う。
BILLING_STATUSES = frozenset({401, 402, 403})

# 通知に載せるレスポンス本文の長さ。長すぎると LINE / Slack で読めなくなる。
BODY_PREVIEW_CHARS = 200

_WHITESPACE = re.compile(r"\s+")


def _preview(raw: object) -> str:
    """レスポンス本文を1行・先頭 BODY_PREVIEW_CHARS 文字に畳む（通知に載せる用）。"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > BODY_PREVIEW_CHARS:
        return text[:BODY_PREVIEW_CHARS] + "…"
    return text


class UnexpectedBody(ValueError):
    """HTTP は成功したが、本文が想定した形ではなかったことを表す例外。

    ステータス（200 など）と本文を一緒に持ち歩くためだけの器。素の ValueError を投げると
    describe() がステータスを拾えず、通知に「（なし＝通信失敗・タイムアウト）」と出てしまう
    （通信は成功しているので、読む人の調べる先が変わってしまう）。

    ValueError を継承しているので、既存の `except ValueError` はそのまま効く。
    """

    def __init__(self, message: str, *, status: int | None = None, body: object = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class QueryFailure:
    """Supabase 照会が失敗した理由（通知に載せられる形）。"""

    status: int | None
    body: str
    message: str
    # HTTP は成功していて本文だけが想定外か（第3分類）。通信失敗と混ぜない。
    unexpected_body: bool = False

    @property
    def is_billing(self) -> bool:
        """課金・認証起因（401/402/403）か。再試行しても直らない種類。"""
        return self.status in BILLING_STATUSES

    @property
    def status_text(self) -> str:
        """通知に出す HTTP ステータスの表記。

        「取れなかった（通信失敗）」と「取れたが本文が想定外」を必ず書き分ける。
        両方を「（なし）」で済ませると、通信できているのにネットワークを疑わせてしまう。
        """
        if self.unexpected_body:
            known = str(self.status) if self.status is not None else "不明"
            return f"{known}（通信は成功。本文が想定外の形）"
        if self.status is None:
            return "（なし＝通信失敗・タイムアウト）"
        return str(self.status)

    def cause_line(self, fallback: str) -> str:
        """通知の1行目に置く「推定原因」。

        課金・認証起因のときは fallback（＝ワークフローが持っていた固定文。
        今回ハズレだった「PC停止 / Render障害 / cron-job.org障害」など）を**出さない**。
        誤った原因を並べると、読む人がそちらを調べに行って時間を失うため。
        """
        if self.unexpected_body:
            # ここも fallback（PC停止 / Ollama不調 など）は出さない。通信は成功しており、
            # PC もローカル生成も無関係だから。調べるべきは応答を返した側の中身。
            where = f"HTTP {self.status} で" if self.status is not None else ""
            return (
                f"🔴 Supabase の応答が{where}想定外の形でした。"
                "監視は判定できていません（通信自体は成功しています）。"
            )
        if self.is_billing:
            # 誤った原因（PC停止 / Render障害 / cron-job.org障害 / Ollama不調）は**1つも書かない**。
            # 「〜ではありません」と書いて否定するのも避ける。通知をスマホで斜め読みすると
            # 否定が飛んで、結局ハズレの原因を調べに行ってしまうため。
            return (
                f"🔴 Supabase が {self.status} を返しています。"
                "プロジェクトが停止している可能性があります"
                "（課金・クォータ・認証キーの問題）。"
            )
        return fallback

    def detail_lines(self, *, include_body: bool = True) -> list[str]:
        """通知本文に差し込む明細（detail が空にならないようにするのが目的）。

        include_body=False は「誰でも読める場所に出す版」。**このリポジトリは公開**で、
        GITHUB_STEP_SUMMARY も Actions のログもログインなしで読めるため、レスポンス本文
        （プロジェクト内部の情報が混じりうる）はそこへ出さず、非公開の通知（LINE / Slack）
        にだけ載せる。ステータスと例外メッセージは原因追跡に要るので公開側にも残す。
        """
        lines = [
            "Supabase 照会に失敗したため、監視は判定できていません。",
            f"- HTTP ステータス: {self.status_text}",
        ]
        if self.body:
            if include_body:
                lines.append(f"- レスポンス本文(先頭{BODY_PREVIEW_CHARS}字): {self.body}")
            else:
                lines.append(
                    "- レスポンス本文: 通知(LINE/Slack)にだけ載せています"
                    "（このリポジトリは公開のため、ここには出しません）"
                )
        lines.append(f"- 例外: {self.message}")
        if self.is_billing:
            lines.append(
                "- 確認先: Supabase ダッシュボードの Usage / Billing"
                "（cached egress・Storage 容量の超過で停止していないか）"
            )
        if self.unexpected_body:
            lines.append(
                "- 確認先: 上のステータスのとおり応答は届いています。"
                "PC・Ollama・ネットワークではなく、返ってきた本文の中身を見ること。"
            )
        return lines

    def detail(self, *, include_body: bool = True) -> str:
        return "\n".join(self.detail_lines(include_body=include_body))


def describe(err: BaseException | None) -> QueryFailure:
    """例外から QueryFailure を組み立てる。

    urllib.error.HTTPError はファイルライクなので `.code` と `.read()` を持つ。
    本文は一度しか読めないため、**例外を掴んだ直後に1回だけ**呼ぶこと
    （2回目は空になり、通知から本文が消える）。
    """
    if err is None:
        return QueryFailure(status=None, body="", message="(例外情報なし)")

    if isinstance(err, UnexpectedBody):
        # 第3分類。ステータスも本文も例外が持って来ているので read() は呼ばない。
        return QueryFailure(
            status=err.status if isinstance(err.status, int) else None,
            body=_preview(err.body),
            message=str(err) or type(err).__name__,
            unexpected_body=True,
        )

    status = getattr(err, "code", None)
    if not isinstance(status, int):
        status = None

    # json.JSONDecodeError も ValueError。ここに来ている時点で HTTP 応答は最後まで
    # 受け取れている（読めなかったのは中身）ので、通信失敗と同じ文言にはしない。
    unexpected_body = isinstance(err, ValueError)

    body = ""
    read = getattr(err, "read", None)
    if callable(read):
        try:
            body = _preview(read())
        except Exception:  # noqa: BLE001 — 本文が読めなくても通知は出す
            body = ""

    return QueryFailure(
        status=status,
        body=body,
        message=str(err) or type(err).__name__,
        unexpected_body=unexpected_body,
    )


def is_billing_error(err: BaseException | None) -> bool:
    """再試行しても直らない失敗（401/402/403）か。

    `describe()` と違い**レスポンス本文を読まない**。本文は一度しか読めないので、
    「まず再試行の可否だけ判定し、本文の取り出しは後で1回だけ行う」経路のために分けてある。
    """
    status = getattr(err, "code", None)
    return isinstance(status, int) and status in BILLING_STATUSES


class QueryFailed(Exception):
    """照会に失敗したことを呼び出し元（main）まで運ぶ例外。

    以前は照会関数の中で `sys.exit(1)` していたため、main が持っている
    「detail / cause を GITHUB_OUTPUT へ書く」処理に到達できず通知が空になっていた。
    落ちる場所を main に一本化するためだけの器。
    """

    def __init__(self, failure: QueryFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure
