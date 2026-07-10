"""data ドメインの Blueprint 定義 + 集約ポイント（B8 route split）。

このモジュールは Blueprint `bp` とルート `/`（index）だけを持ち、実際の
データ系ハンドラは役割ごとに分割した以下のモジュールが同じ `bp` に生やす:

- data_range.py … /api/current, /api/range, /api/range_multi（時系列取得 + キャッシュ）
- data_meta.py  … /api/meta, /api/holiday_status, /api/second_venues（メタ情報）

末尾の副作用 import が create_app の register_blueprint より前に走ることで、
分割先ハンドラも漏れなく `bp` に登録される（URL / エンドポイント名は不変）。
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, render_template

from ..utils import storage
from .common import get_config as _config

bp = Blueprint("data", __name__)


@bp.get("/")
def index() -> str | Response:
    try:
        return render_template("index.html")
    except Exception:  # pragma: no cover
        cfg = _config()
        return jsonify({"msg": "index.html missing", "current": storage.load_latest(cfg)})


# 分割先モジュールを import して、そのハンドラを上の `bp` に登録する（副作用 import）。
# data_range / data_meta は `from .data import bp` で同じ Blueprint を掴むため、
# ここで import しておかないと register_blueprint の時点でルートが url_map から欠落する。
from . import data_meta, data_range  # noqa: E402,F401
