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
# 让 `from pipeline import browser_cookies` 可用（standalone 运行时 cwd 会被切走）
sys.path.insert(0, str(Path(__file__).resolve().parent))
# sign.js / a_bogus.js 在 liveMan 里按相对文件名读取，需要把 cwd 切到内核目录
os.chdir(_VENDOR)

import gzip  # noqa: E402
import re  # noqa: E402

from liveMan import DouyinLiveWebFetcher  # noqa: E402

from pipeline import browser_cookies  # noqa: E402
from pipeline.runtime_health import classify_room_page  # noqa: E402
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


def _decode_unicode_escapes(s: str) -> str:
    r"""把残留的 \uXXXX 还原成字符（昵称里偶有），只动 \uXXXX，CJK 直出不受影响。"""
    if "\\u" not in s:
        return s
    try:
        return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    except (ValueError, TypeError):
        return s


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

CREATE TABLE IF NOT EXISTS room_meta (
    live_id    TEXT PRIMARY KEY,
    nickname   TEXT,
    updated_ts INTEGER
);
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

    def set_room_meta(self, live_id: str, nickname: str) -> None:
        """记录/更新房间的主播昵称（来自房间页解析）。空昵称跳过，避免覆盖已有。"""
        if not nickname:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO room_meta(live_id, nickname, updated_ts) VALUES (?,?,?) "
                "ON CONFLICT(live_id) DO UPDATE SET "
                "nickname=excluded.nickname, updated_ts=excluded.updated_ts",
                (str(live_id or ""), nickname, int(time.time())),
            )
            self._conn.commit()

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
        self._room_status: int | None = None  # 房间页 room.status：2=在播，其余=已下播/未开播
        self._anchor_nick: str | None = None   # 房间页解析的主播昵称（导出区分房间用）
        self._page_state = "unknown"
        # a_bogus.js 用绝对路径，避免 cwd 变化导致找不到
        self.abogus_file = str(_VENDOR / "a_bogus.js")
        # 注入浏览器铸的信任 cookie，过抖音风控验证墙。导航到本房间页铸造。
        jar = browser_cookies.cached_jar()
        tt = jar.get("ttwid", "")
        self._cached_ttwid = tt
        if tt:
            # 让 self.ttwid 直接返回铸好的值，不再裸请求（裸请求会拿回验证页 cookie）
            self._DouyinLiveWebFetcher__ttwid = tt
        for k, v in jar.items():
            self.session.cookies.set(k, v)

    def _rid(self) -> str:
        return self.__dict__.get("_DouyinLiveWebFetcher__room_id") or ""

    @property
    def ttwid(self) -> str:
        """Return cached trusted ttwid only; background workers never mint one."""
        return self._cached_ttwid

    def _fetch_room_page(self, cookie_header: str) -> tuple[str | None, int | None, str | None]:
        """带指定 cookie 抓房间页，解析 (roomId, room.status, 主播昵称)。抓不到（验证页）返回 (None, None, None)。

        三者同源取自 roomStore→roomInfo（与前端 parseLiveHtml 一致）：
          room.status：2=直播中，其余（含取不到）按已下播/未开播处理。关键：房间页在主播
                       下播后仍会短暂保留 roomId，单看 roomId 不能判断在播，必须读 status。
          anchor.nickname：主播昵称，导出时用来区分各房间。
        """
        try:
            headers = dict(self.headers)
            headers["Referer"] = self.live_url
            headers["cookie"] = cookie_header
            resp = self.session.get(
                self.live_url + self.live_id,
                headers=headers,
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            return None, None, None
        text = resp.text
        self._page_state = classify_room_page(text)
        m = re.search(r'roomId..:..(\d+)', text)
        rid = m.group(1) if m else None
        unesc = text.replace('\\"', '"')  # 页面 JSON 转义，先还原再按链定位
        sm = re.search(
            r'"roomStore":\{.*?"roomInfo":\{.*?"room":\{.*?"status":(\d)',
            unesc, re.DOTALL,
        )
        status = int(sm.group(1)) if sm else None
        nm = re.search(
            r'"roomInfo":\{.*?"anchor":\{.*?"nickname":"(.*?)"',
            unesc, re.DOTALL,
        )
        nick = _decode_unicode_escapes(nm.group(1)) if nm else None
        return rid, status, nick

    @property
    def room_id(self) -> str | None:
        """覆写基类：用整套浏览器 cookie 过墙；验证失败交给用户主动重铸。

        后台线程绝不自动弹浏览器。自动强制重铸会让多个离线房间反复打开验证窗口，
        同时持续撞验证墙；管理器会识别 page_state=challenge 并进入全局冷却。
        """
        cached = self.__dict__.get("_DouyinLiveWebFetcher__room_id")
        if cached:
            return cached
        rid, status, nick = self._fetch_room_page(browser_cookies.cached_cookie_header())
        self._DouyinLiveWebFetcher__room_id = rid
        self._room_status = status
        self._anchor_nick = nick
        return rid

    @property
    def page_state(self) -> str:
        return self._page_state

    @property
    def anchor_nick(self) -> str:
        """主播昵称；依赖 room_id 触发的同一次取页解析并缓存，不额外发请求。"""
        if self._anchor_nick is None:
            _ = self.room_id
        return self._anchor_nick or ""

    @property
    def is_live(self) -> bool:
        """房间页 room.status==2 视为在播；取不到或非 2 视为已下播/未开播。

        依赖 room_id 触发的同一次取页（status 与 roomId 一起解析并缓存），不额外发请求。
        """
        if self._room_status is None:
            _ = self.room_id
        return self._room_status == 2

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
