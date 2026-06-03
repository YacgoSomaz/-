"""最小后端 worker（技术验证）：

输入一个抖音直播号(web_rid) -> 用 saermart 内核获取 room_id -> 连 WSS ->
protobuf 解析 -> 把 chat/gift/member/like/social/stat 等事件写入独立 SQLite。

刻意保持最小：
  - 不接 UI、不并发、不动 BatchView。
  - 写入独立的 worker_events.db（验证期隔离，避免污染 danmu.db）；
    接回现有库是后续"适配层"步骤。
  - 无重连（run_forever 维持单连接，断开即结束本次验证）。

用法：
    python run_worker.py <直播号> [--seconds N] [--db path]
例：
    python run_worker.py 123456789 --seconds 300
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

# Windows 下 stdout 默认走 GBK 严格编码，遇到 emoji/CJK 会抛 UnicodeEncodeError，
# 进而崩掉基类 liveMan.py 的心跳打印线程。重配为 UTF-8/replace，覆盖所有打印（含 vendor）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# vendored saermart 内核目录
_VENDOR = Path(__file__).resolve().parent / "vendor" / "DouyinLiveWebFetcher"
if not _VENDOR.exists():
    raise SystemExit(f"未找到内核目录: {_VENDOR}")

# 让 `from protobuf.douyin import *` / `from ac_signature import ...` / `import liveMan` 可用
sys.path.insert(0, str(_VENDOR))
# sign.js / a_bogus.js 在 liveMan 里按相对文件名读取，需要把 cwd 切到内核目录
os.chdir(_VENDOR)

import gzip  # noqa: E402

from liveMan import DouyinLiveWebFetcher  # noqa: E402
from protobuf.douyin import (  # noqa: E402
    ChatMessage,
    GiftMessage,
    LikeMessage,
    MemberMessage,
    SocialMessage,
    RoomUserSeqMessage,
    FansclubMessage,
    ControlMessage,
    PushFrame,
    Response,
)

# 诊断日志：把每条消息的 method 统计写到 UTF-8 文件，绕开 Windows 控制台 GBK 乱码，
# 用于判断 total=0 到底是房间没流量 还是 落库有 bug。
_DIAG_PATH = Path(__file__).resolve().parent / "_diag.log"


def _diag(msg: str) -> None:
    with open(_DIAG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# 事件库的 schema
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    TEXT,
    live_id    TEXT,
    event_type TEXT,
    user_id    TEXT,
    user_name  TEXT,
    content    TEXT,
    extra      TEXT,
    ts         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ev_room ON events(room_id);
CREATE INDEX IF NOT EXISTS idx_ev_type ON events(event_type);
"""


class SqliteSink:
    """线程安全的事件落库（websocket 回调在子线程触发）。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()
        self.counts: dict[str, int] = {}

    def emit(
        self,
        *,
        room_id: str,
        live_id: str,
        event_type: str,
        user_id: str = "",
        user_name: str = "",
        content: str = "",
        extra: dict | None = None,
    ) -> None:
        ts = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(room_id, live_id, event_type, user_id, user_name, content, extra, ts)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(room_id or ""),
                    str(live_id or ""),
                    event_type,
                    str(user_id or ""),
                    str(user_name or ""),
                    content or "",
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    ts,
                ),
            )
            self._conn.commit()
            self.counts[event_type] = self.counts.get(event_type, 0) + 1

    def total(self) -> int:
        return sum(self.counts.values())

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class WorkerFetcher(DouyinLiveWebFetcher):
    """在 saermart 内核上覆写各解析方法 -> 落库（仍保留控制台打印便于观察）。"""

    def __init__(self, live_id: str, sink: SqliteSink) -> None:
        super().__init__(live_id)
        self._sink = sink
        self._method_counts: dict[str, int] = {}
        # a_bogus.js 用绝对路径，避免 cwd 变化导致找不到
        self.abogus_file = str(_VENDOR / "a_bogus.js")

    def _rid(self) -> str:
        return self.__dict__.get("_DouyinLiveWebFetcher__room_id") or ""

    # ---- 诊断：覆写 onOpen / onMessage，统计所有 method 类型 ----
    def _wsOnOpen(self, ws):
        _diag("【√】WebSocket连接成功")
        super()._wsOnOpen(ws)

    def _wsOnMessage(self, ws, message):
        try:
            package = PushFrame().parse(message)
            response = Response().parse(gzip.decompress(package.payload))
            if response.need_ack:
                import websocket as _ws
                ack = PushFrame(
                    log_id=package.log_id,
                    payload_type="ack",
                    payload=response.internal_ext.encode("utf-8"),
                ).SerializeToString()
                ws.send(ack, _ws.ABNF.OPCODE_BINARY)
            for msg in response.messages_list:
                method = msg.method
                self._method_counts[method] = self._method_counts.get(method, 0) + 1
                handler = {
                    "WebcastChatMessage": self._parseChatMsg,
                    "WebcastGiftMessage": self._parseGiftMsg,
                    "WebcastLikeMessage": self._parseLikeMsg,
                    "WebcastMemberMessage": self._parseMemberMsg,
                    "WebcastSocialMessage": self._parseSocialMsg,
                    "WebcastRoomUserSeqMessage": self._parseRoomUserSeqMsg,
                    "WebcastFansclubMessage": self._parseFansclubMsg,
                    "WebcastControlMessage": self._parseControlMsg,
                }.get(method)
                if handler:
                    try:
                        handler(msg.payload)
                    except Exception as e:  # 解析单条失败不影响整体
                        _diag(f"【X】parse {method} 失败: {e!r}")
        except Exception as e:
            _diag(f"【X】_wsOnMessage 失败: {e!r}")

    # ---- 覆写解析：解析 + 落库 ----
    def _parseChatMsg(self, payload):
        m = ChatMessage().parse(payload)
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="chat",
            user_id=m.user.id, user_name=m.user.nick_name, content=m.content,
        )

    def _parseGiftMsg(self, payload):
        m = GiftMessage().parse(payload)
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="gift",
            user_id=m.user.id, user_name=m.user.nick_name, content=m.gift.name,
            extra={"gift_name": m.gift.name, "combo_count": m.combo_count},
        )

    def _parseLikeMsg(self, payload):
        m = LikeMessage().parse(payload)
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="like",
            user_id=m.user.id, user_name=m.user.nick_name, content=str(m.count),
            extra={"count": m.count},
        )

    def _parseMemberMsg(self, payload):
        m = MemberMessage().parse(payload)
        gender = ["女", "男"][m.user.gender] if m.user.gender in (0, 1) else ""
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="member",
            user_id=m.user.id, user_name=m.user.nick_name, content="进入直播间",
            extra={"gender": gender},
        )

    def _parseSocialMsg(self, payload):
        m = SocialMessage().parse(payload)
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="social",
            user_id=m.user.id, user_name=m.user.nick_name, content="关注了主播",
        )

    def _parseRoomUserSeqMsg(self, payload):
        m = RoomUserSeqMessage().parse(payload)
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="stat",
            content=f"current={m.total};total_pv={m.total_pv_for_anchor}",
            extra={"current": m.total, "total_pv": m.total_pv_for_anchor},
        )

    def _parseFansclubMsg(self, payload):
        m = FansclubMessage().parse(payload)
        self._sink.emit(
            room_id=self._rid(), live_id=self.live_id, event_type="fansclub",
            content=m.content,
        )

    def _parseControlMsg(self, payload):
        m = ControlMessage().parse(payload)
        if m.status == 3:
            _diag(f"【控制】room_id={self._rid()} 直播间已结束")
            self.stop()

    # 验证期不调用 get_room_status（需要 a_bogus，断开时易抛错），仅记录
    def _wsOnClose(self, ws, *args):
        _diag(f"【关闭】room_id={self._rid()} WebSocket 连接关闭")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("live_id", help="抖音直播号 (web_rid)")
    parser.add_argument("--seconds", type=int, default=300, help="运行多少秒后自动停止")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent / "worker_events.db"),
        help="事件库路径",
    )
    args = parser.parse_args()

    sink = SqliteSink(args.db)
    fetcher = WorkerFetcher(args.live_id, sink)

    print(f"[worker] live_id={args.live_id}")
    rid = fetcher.room_id
    print(f"[worker] room_id={rid}")
    if not rid:
        print("[worker] 未取到 room_id（可能未开播/风控/解析失败），退出。")
        sink.close()
        return 2

    # 定时停止：到点关闭 ws，让 run_forever 返回
    def _stopper():
        time.sleep(args.seconds)
        print(f"[worker] 到达 {args.seconds}s，停止。")
        try:
            fetcher.stop()
        except Exception:
            pass

    threading.Thread(target=_stopper, daemon=True).start()

    try:
        fetcher.start()  # 阻塞直到 ws 关闭
    except KeyboardInterrupt:
        fetcher.stop()
    finally:
        _diag(f"[worker] 收到的 method 类型统计: {fetcher._method_counts}")
        _diag(f"[worker] 落库统计: total={sink.total()} 明细={sink.counts}")
        print(f"[worker] 落库统计: total={sink.total()} 明细={sink.counts}")
        sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
