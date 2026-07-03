# ============================================================================
# 復旧用ミラー (recovery mirror) — 正本は下記の共有パスにあり、音楽プロジェクトと
# 共有している単一ソースです。本ファイルはマシン故障時の復旧用スナップショットで、
# 実行時に import されるのは正本のほう (各スクリプトが sys.path で下記を指す):
#     C:\Users\Public\共有データ系\gpu_lock.py
# 正本を更新したら、このミラーも更新すること (drift 注意)。
# ============================================================================
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共有GPU 排他ロック（クロスプロジェクト用・単一ソース）

このマシンの GPU は 1枚(RTX 4060 8GB)を複数プロジェクトで共有している:
  - めぐりび: ローカルLLM(Ollama)で日次/週次/比較記事を生成（単発・非常駐）
  - 小林武史アレンジ: 音楽生成モデル（単発・非常駐）
どちらも「常駐しない」が、同じ瞬間に両方が起動すると 8GB を食い合って OOM しうる。
このモジュールは両者が尊重する 1個のファイルロックを提供し、
「GPUを使う時は必ずロックを取ってから」にすることで衝突を仕組みで防ぐ。

使い方（両プロジェクト共通）:
    import sys; sys.path.insert(0, r"C:\\Users\\Public\\共有データ系")
    import gpu_lock

    with gpu_lock.acquire(owner="meguribi-report", timeout=600):
        # ここで Ollama や音楽生成など GPU を使う処理
        ...
    # with を抜けると自動解放。例外時も解放される。

CLI:
    python gpu_lock.py status              # 誰が持っているか / 空きVRAM を表示
    python gpu_lock.py hold --owner test --seconds 15   # 動作確認用に一定時間保持

設計:
  - os.open(O_CREAT|O_EXCL) による原子的作成でロック取得（Windows/Unix 両対応）。
  - ロックファイルに JSON {owner, pid, host, acquired_at} を書く（観測用）。
  - stale 対策: acquired_at が STALE_SEC より古ければ「持ち主がクラッシュした」とみなし奪取。
  - stdlib のみ。GPU が無くてもロック自体は動く（VRAM表示は nvidia-smi があれば付加）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# 既定のロックファイル位置（両プロジェクトが同じパスを見る）。環境変数で上書き可。
LOCK_PATH = Path(os.getenv("SHARED_GPU_LOCK", r"C:\Users\Public\共有データ系\.gpu_shared.lock"))
STALE_SEC = int(os.getenv("SHARED_GPU_LOCK_STALE_SEC", "1200"))  # 20分で stale とみなし奪取
POLL_SEC = 2.0


def _now() -> float:
    return time.time()


def _read_lock() -> dict | None:
    try:
        return json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_lock_atomic(payload: dict) -> bool:
    """O_EXCL で原子的に作成。既に存在すれば False。"""
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except Exception:
        return False
    try:
        os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _pid_alive(pid: int) -> bool:
    """pid のプロセスが生きているか（best-effort）。判定不能時は安全側で True
    （生きているとみなして奪取しない＝LIVEロックを誤って奪う事故を防ぐ）。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False  # 開けない = そのpidは存在しない
            try:
                code = ctypes.c_ulong()
                if k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return True  # 判定不能 -> 安全側
            finally:
                k.CloseHandle(h)
        except Exception:
            return True  # 判定不能 -> 安全側（奪わない）
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _is_stale(info: dict | None) -> bool:
    if not info:
        return True
    ts = info.get("acquired_at")
    if not isinstance(ts, (int, float)):
        return True
    # 同一ホストで保持者プロセスが既に死んでいれば即 stale（時間切れを待たず奪取）。
    # 別ホストや判定不能時は下の時間ベースにフォールバック（LIVEロックの誤奪取を避ける）。
    if info.get("host") == socket.gethostname():
        pid = info.get("pid")
        if isinstance(pid, int) and not _pid_alive(pid):
            return True
    return (_now() - ts) > STALE_SEC


def _try_take(owner: str) -> bool:
    payload = {
        "owner": owner,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "acquired_at": _now(),
    }
    if _write_lock_atomic(payload):
        return True
    # 既存ロックが stale なら奪取（削除して作り直し）
    info = _read_lock()
    if _is_stale(info):
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            return False
        return _write_lock_atomic(payload)
    return False


def try_acquire(owner: str = "unknown") -> bool:
    """ノンブロッキングで1回だけ取得を試みる。取れたら True。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _try_take(owner)


def release(owner: str | None = None) -> None:
    """ロック解放。owner 指定時は自分が持っている場合のみ削除（他者のを消さない）。"""
    info = _read_lock()
    if info is None:
        return
    if owner is not None and info.get("owner") != owner and info.get("pid") != os.getpid():
        return  # 自分のロックでなければ触らない
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


@contextmanager
def acquire(owner: str = "unknown", timeout: float = 600.0, poll: float = POLL_SEC):
    """with 文で使う。timeout 秒まで待って取得。取れなければ TimeoutError。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = _now() + timeout
    waited = False
    while True:
        if _try_take(owner):
            break
        if _now() >= deadline:
            holder = _read_lock() or {}
            raise TimeoutError(
                f"GPU lock busy (held by owner={holder.get('owner')} pid={holder.get('pid')} "
                f"since {int(_now() - (holder.get('acquired_at') or _now()))}s ago); waited {int(timeout)}s"
            )
        if not waited:
            holder = _read_lock() or {}
            print(f"[gpu_lock] waiting... held by {holder.get('owner')} (pid={holder.get('pid')})", flush=True)
            waited = True
        time.sleep(poll)
    try:
        yield
    finally:
        release(owner=owner)


def gpu_free_mb() -> int | None:
    """nvidia-smi があれば空きVRAM(MiB)を返す。無ければ None。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode == 0:
            return int(out.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def status() -> dict:
    info = _read_lock()
    return {
        "lock_path": str(LOCK_PATH),
        "held": info is not None and not _is_stale(info),
        "holder": info,
        "stale": _is_stale(info) if info else None,
        "gpu_free_mb": gpu_free_mb(),
    }


def _cli() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if cmd == "hold":
        owner = "test"
        seconds = 10.0
        for i, a in enumerate(args):
            if a == "--owner" and i + 1 < len(args):
                owner = args[i + 1]
            if a == "--seconds" and i + 1 < len(args):
                seconds = float(args[i + 1])
        print(f"[gpu_lock] acquiring as owner={owner} ...")
        with acquire(owner=owner, timeout=30):
            print(f"[gpu_lock] HELD for {seconds}s (free VRAM: {gpu_free_mb()} MiB)")
            time.sleep(seconds)
        print("[gpu_lock] released")
        return 0
    if cmd == "release-force":
        try:
            LOCK_PATH.unlink(missing_ok=True)
            print("[gpu_lock] force-removed lock file")
        except Exception as e:  # noqa: BLE001
            print("err", e)
        return 0
    print("usage: gpu_lock.py [status|hold --owner NAME --seconds N|release-force]")
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
