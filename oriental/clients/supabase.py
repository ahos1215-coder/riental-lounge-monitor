"""Supabase の叩き方（認証ヘッダ / Storage オブジェクト URL / Storage の単純 GET）を1箇所に集約する。

「どのキーをどのヘッダに入れるか」「Storage の URL はどう組み立てるか」が
6ファイルに手書きコピーされていたため、書き間違い（apikey 抜け・prefix の
二重スラッシュ）を1箇所で検証できるようにするのが目的。

呼び出し元ごとに異なるリトライ方針・例外の握り方・disk cache fallback は
ここには持ち込まない（それぞれの呼び出し元の事情なので、そのまま各所に残す）。
stdlib のみに依存する（requests を使う呼び出し元は URL/ヘッダだけを借りる）。

**バッチ側（scripts/）には同じものが別実装で存在する**: `scripts/_supabase_common.py` の
`auth_headers` / `NOT_FOUND_BODY_MARKERS`。scripts/ は GHA の最小依存環境（flask を
install しない）でも動く必要があり、この oriental パッケージを import できないため。
シグネチャ・返り値・判定文字列は同一で、tests/test_scripts_auth_headers_ssot.py と
tests/test_storage_not_found_markers.py が一致を固定する。片方を変えたら両方直すこと。
再試行方針だけは意図的に非対称（oriental/clients/http.py の注記を参照）。
"""

from __future__ import annotations

# Supabase Storage が「オブジェクトが無い」を HTTP 400 のボディで伝えてくるときの目印
# （小文字化した本文に対する部分一致）。
# ★鏡像注意★ scripts/_supabase_common.py の NOT_FOUND_BODY_MARKERS と同一。片方を
# 変えたら必ず両方直すこと（片方だけ直すと「モデル/テンプレが無い」の誤判定が片系統に
# だけ残り、2026-08-18 の事故と同じ見えにくい壊れ方をする）。
# 両者の一致は tests/test_storage_not_found_markers.py が固定する。
NOT_FOUND_BODY_MARKERS = ("not_found", "not found", "object not found")


def auth_headers(
    key: str, *, accept_json: bool = False, content_type: bool = False
) -> dict[str, str]:
    """Supabase REST / Storage 共通の認証ヘッダ。

    service role key は `apikey` と `Authorization: Bearer` の両方に必要
    （どちらか片方だけだと PostgREST / Storage が 401 を返す）。
    """
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if accept_json:
        headers["Accept"] = "application/json"
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def storage_object_url(base_url: str, bucket: str, path: str) -> str:
    """`<base>/storage/v1/object/<bucket>/<path>` を組み立てる（余分なスラッシュを潰す）。"""
    base = (base_url or "").rstrip("/")
    bucket_part = (bucket or "").strip("/")
    path_part = (path or "").strip("/")
    return f"{base}/storage/v1/object/{bucket_part}/{path_part}"


def storage_get_bytes(
    base_url: str,
    key: str,
    bucket: str,
    path: str,
    *,
    timeout: float = 10,
) -> bytes | None:
    """Storage のオブジェクトを生バイト列で取得する。

    オブジェクトが存在しない場合（404、または Supabase が 400 で返す "not found" 系）は
    None を返し、それ以外の HTTP エラー・ネットワークエラーは呼び出し側へ伝播させる
    （握りつぶすかどうかは呼び出し側の方針に委ねる）。
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        storage_object_url(base_url, bucket, path), headers=auth_headers(key)
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 400:
            try:
                body = exc.read().decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                body = ""
            if any(marker in body for marker in NOT_FOUND_BODY_MARKERS):
                return None
        raise
