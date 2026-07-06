"""高并发测试 worker：同 IP 下并发监听 N 个直播间，观察是否触发风控。

风控判定信号（按严重度）：
  - ttwid 为空            -> 首页就被拦（最严重）
  - 取不到 room_id        -> /{live_id} 页面被风控/未开播
  - WS 建连失败/秒断       -> 签名或握手被拒
  - 正常落库              -> 未被风控

设计要点（降低风控）：
  - 错开启动（--stagger 秒），避免 N 个连接瞬时突发，像机器人
  - 每房间独立线程跑 run_forever（websocket-client 是阻塞同步的）
  - 共享一个线程安全 SqliteSink（按 live_id 区分事件）
  - 建连只拉一次 room_id，之后是静默长连，几乎不再碰风控面

用法：
    python run_multi.py 123 456 789 ... --seconds 180 --stagger 3
"""

from __future__ import annotations

import argparse
import sqlite3
import threading
import time
from pathlib import Path

from pipeline.danmu_backend import create_fetcher
from pipeline.event_sink import SqliteSink


def _run_room(
    live_id: str,
    sink: SqliteSink,
    seconds: int,
    status: dict[str, str],
    lock: threading.Lock,
) -> None:
    """单房间线程：取 room_id -> 建连 -> 定时停止。状态写入共享 status。"""
    def _set(s: str) -> None:
        with lock:
            status[live_id] = s

    try:
        fetcher = create_fetcher(live_id, sink)
    except Exception as e:  # noqa: BLE001
        _set(f"初始化异常: {e!r}")
        return

    rid = fetcher.room_id or ""

    _set(f"room_id={rid or '?'} 连接中")

    def _stopper() -> None:
        time.sleep(seconds)
        try:
            fetcher.stop()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_stopper, daemon=True).start()

    try:
        fetcher.start()  # 阻塞直到 ws 关闭
        _set(f"room_id={fetcher.room_id or rid or '?'} 正常结束")
    except Exception as e:  # noqa: BLE001
        _set(f"room_id={rid} 运行异常: {e!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("live_ids", nargs="+", help="多个抖音直播号 (web_rid)")
    parser.add_argument("--seconds", type=int, default=180, help="每个房间运行多少秒")
    parser.add_argument("--stagger", type=float, default=3.0, help="房间间错开启动秒数")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent / "multi_events.db"),
        help="事件库路径",
    )
    args = parser.parse_args()

    db_path = str(Path(args.db).resolve())
    sink = SqliteSink(db_path)
    status: dict[str, str] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    print(f"[multi] 并发 {len(args.live_ids)} 个房间, 每个 {args.seconds}s, 错开 {args.stagger}s")
    t0 = time.time()
    for lid in args.live_ids:
        t = threading.Thread(target=_run_room, args=(lid, sink, args.seconds, status, lock))
        t.start()
        threads.append(t)
        time.sleep(args.stagger)  # 错开，避免突发

    for t in threads:
        t.join()
    elapsed = time.time() - t0

    # 按 live_id 汇总落库量
    conn = sqlite3.connect(db_path)
    per_room = dict(
        conn.execute("SELECT live_id, COUNT(*) FROM events GROUP BY live_id").fetchall()
    )
    conn.close()

    print(f"\n[multi] ==== 结果 (耗时 {elapsed:.0f}s) ====")
    ok = 0
    for lid in args.live_ids:
        cnt = per_room.get(lid, 0)
        st = status.get(lid, "未知")
        flag = "✓" if cnt > 0 else "✗"
        if cnt > 0:
            ok += 1
        print(f"  {flag} {lid}: events={cnt} | {st}")
    print(f"[multi] 成功落库房间: {ok}/{len(args.live_ids)}  总事件={sink.total()}")
    sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
