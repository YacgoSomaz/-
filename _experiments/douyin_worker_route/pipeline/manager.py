"""房间管理器：可按房间启停的「弹幕 + 音频 + 转写」托管核心。

给 Web 控制台用——orchestrator 是一次性命令行版，这里是可交互、可热增删房间的常驻版。

线程模型：
  每房间一条弹幕长连线程（并发 WSS，断线自动重连）。
  每房间一条音频线（房间已连接时连续录段，避免同主播话术漏录）。
  全局一条转写线（常驻轮询 pending）。

房间列表持久化到 rooms.json，重启后可恢复。状态全部在内存里，Web 层轮询读取。
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from run_worker import WorkerFetcher, SqliteSink  # noqa: E402

from . import browser_cookies, config
from .audio_capture import record_room_muxer
from .sensevoice_engine import SenseVoiceEngine
from .speaker_worker import process_once as process_speakers_once
from .runtime_health import ErrorRegistry, GlobalCooldown
from .transcribe_batch import process_once
from .transcript_store import TranscriptStore

ROOMS_JSON = config.ROOMS_JSON
# 退避分两类，绝不混用：未开播/无 room_id 必须长退避，否则 N 个未播房间 5 秒一轮
# 持续打房间页，会把后端自己送进风控；带抖动错开各房间，避免同一时刻齐发。
NOT_LIVE_BACKOFF_SEC = 90       # 未开播/取不到 room_id/连接前异常：长退避基准
NOT_LIVE_JITTER_SEC = 60        # 长退避随机抖动上限
RECONNECT_BACKOFF_SEC = 8       # 已连接后真断线：短退避基准
RECONNECT_JITTER_SEC = 7        # 短退避随机抖动上限
MAX_ACTIVE_ROOMS = 10           # 同时活跃连接封顶；高并发测试时留意验证页与取流失败率
RISK_COOLDOWN_SEC = 15 * 60     # 任一房间命中验证墙后，所有房间暂停页面请求
COOKIE_MISSING_BACKOFF_SEC = 5 * 60
TRANSCRIBE_POLL_SEC = 10
TRANSCRIBE_INIT_RETRY_SEC = 30
AUDIO_IDLE_SLEEP_SEC = 3
AUDIO_FAIL_BACKOFF_SEC = 12


@dataclass
class RoomState:
    """单房间运行态。线程与事件不参与序列化。"""

    rid: str
    anchor_name: str = ""
    avatar_url: str = ""
    source_url: str = ""
    sec_user_id: str = ""
    active: bool = False
    status: str = "未启动"
    phase: str = "stopped"
    connected: bool = False
    next_retry_ts: int = 0
    last_segment_ts: int = 0
    thread: threading.Thread | None = field(default=None, repr=False)
    audio_thread: threading.Thread | None = field(default=None, repr=False)
    stop: threading.Event | None = field(default=None, repr=False)


class RoomManager:
    """统一托管多房间的采集线。线程安全，供 Web 层并发调用。"""

    def __init__(self) -> None:
        config.ensure_dirs()
        self._lock = threading.Lock()
        self._rooms: dict[str, RoomState] = {}
        self._sink = SqliteSink(str(config.EVENTS_DB))
        # 录音线与转写线共享同一 TranscriptStore：录音线写 recording_timeline（封口/残段/断档），
        # 转写线读待转写段并回写 transcripts。内部带锁，跨线程安全。
        self._store = TranscriptStore()

        self._workers_started = False
        self._transcribe_stop = threading.Event()
        self._transcribe_thread: threading.Thread | None = None
        self._speaker_stop = threading.Event()
        self._speaker_thread: threading.Thread | None = None
        self._errors = ErrorRegistry()
        self._risk_cooldown = GlobalCooldown()
        self._control_epoch = 0

        self._load_rooms()

    # ---------- 房间列表持久化 ----------

    def _load_rooms(self) -> None:
        if not ROOMS_JSON.exists():
            return
        try:
            ids = json.loads(ROOMS_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in ids:
            if isinstance(item, dict):
                rid = str(item.get("rid") or "").strip()
                if not rid:
                    continue
                self._rooms[rid] = RoomState(
                    rid=rid,
                    anchor_name=str(item.get("anchor_name") or ""),
                    avatar_url=str(item.get("avatar_url") or ""),
                    source_url=str(item.get("source_url") or ""),
                    sec_user_id=str(item.get("sec_user_id") or ""),
                )
            else:
                rid = str(item).strip()
                if rid:
                    self._rooms[rid] = RoomState(rid=rid)

    def _save_rooms(self) -> None:
        rooms = [
            {
                "rid": state.rid,
                "anchor_name": state.anchor_name,
                "avatar_url": state.avatar_url,
                "source_url": state.source_url,
                "sec_user_id": state.sec_user_id,
            }
            for state in sorted(self._rooms.values(), key=lambda room: room.rid)
        ]
        try:
            ROOMS_JSON.write_text(json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---------- 全局工作线（音频 + 转写）懒启动 ----------

    def _ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        self._transcribe_thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._transcribe_thread.start()
        self._speaker_thread = threading.Thread(target=self._speaker_loop, daemon=True)
        self._speaker_thread.start()

    def _active_ids(self) -> list[str]:
        with self._lock:
            return [r.rid for r in self._rooms.values() if r.active]

    def _room_audio_loop(self, rid: str, stop: threading.Event) -> None:
        """单房间「零丢失」连续录音：房间保持连接时一条常驻 ffmpeg + segment muxer 连续封口。

        看门狗、残段/断档记账全在 record_room_muxer 内完成；本循环只负责「连接时进入、
        断开时让出」。并发上限由 MAX_ACTIVE_ROOMS 控制；未连接/未开播不取流，避免高频探测。
        禁止同房间双拉：任一时刻该房间只有这一条音频线、一条 ffmpeg。
        """
        def _touch_last_segment() -> None:
            with self._lock:
                if rid in self._rooms:
                    self._rooms[rid].last_segment_ts = int(time.time())

        def _rel_audio_path(path: object) -> str:
            p = Path(str(path))
            try:
                return str(p.resolve().relative_to(config.DATA_DIR.resolve())).replace("\\", "/")
            except (OSError, ValueError):
                return str(p).replace("\\", "/")

        def _on_seal(**kw: object) -> None:
            duration = float(kw.get("duration_sec") or 0)
            status = "ok" if duration >= config.SEGMENT_SEC * 0.75 else "short"
            kw["file_path"] = _rel_audio_path(kw["file_path"])
            self._store.add_segment(room_id=rid, status=status, kind=("short" if status == "short" else "segment"), **kw)  # type: ignore[arg-type]
            _touch_last_segment()

        def _on_partial(**kw: object) -> None:
            kw["file_path"] = _rel_audio_path(kw["file_path"])
            self._store.add_partial(room_id=rid, **kw)  # type: ignore[arg-type]
            _touch_last_segment()

        def _on_gap(**kw: object) -> None:
            self._store.add_gap(room_id=rid, **kw)  # type: ignore[arg-type]

        def _on_risk_control(reason: str) -> None:
            refresh = browser_cookies.auto_refresh(rid, force=True)
            if refresh.get("refreshed"):
                self.clear_risk_cooldown()
                return
            self._risk_cooldown.trigger(RISK_COOLDOWN_SEC, f"房间 {rid} 音频取址命中验证页")
            cooldown = self._risk_cooldown.snapshot()
            with self._lock:
                st = self._rooms.get(rid)
                if st is not None:
                    st.status = reason
                    st.phase = "risk_cooldown"
                    st.next_retry_ts = int(cooldown["until_ts"])

        def _should_stop_audio() -> bool:
            if stop.is_set():
                return True
            with self._lock:
                st = self._rooms.get(rid)
                return not bool(st and st.active and st.connected)

        while not stop.is_set():
            with self._lock:
                st = self._rooms.get(rid)
                should_record = bool(st and st.active and st.connected)
            if not should_record:
                stop.wait(AUDIO_IDLE_SLEEP_SEC)
                continue

            # seq 起号：台账权威 + 文件系统兜底，取大者，保证跨重连/重启严格递增不覆盖。
            start_seq = max(self._store.max_seq(rid) + 1, config.next_segment_number(rid))

            try:
                record_room_muxer(
                    rid,
                    config.AUDIO_DIR / rid,
                    start_seq,
                    _should_stop_audio,
                    on_seal=_on_seal,
                    on_partial=_on_partial,
                    on_gap=_on_gap,
                    can_fetch=lambda: not self._risk_cooldown.active(),
                    on_risk_control=_on_risk_control,
                )
            except Exception as exc:  # noqa: BLE001
                self._errors.record(f"audio:{rid}", exc)
            if stop.is_set():
                return
            stop.wait(AUDIO_FAIL_BACKOFF_SEC)

    def _transcribe_loop(self) -> None:
        engine = None
        while not self._transcribe_stop.is_set():
            if engine is None:
                try:
                    engine = SenseVoiceEngine()
                except Exception as exc:  # noqa: BLE001
                    # 模型首次加载失败不能让转写线程永久死亡。记录到诊断面板，
                    # 退避后持续自愈；录音线程完全不受影响。
                    self._errors.record("transcription:model", exc)
                    self._transcribe_stop.wait(TRANSCRIBE_INIT_RETRY_SEC)
                    continue
            try:
                process_once(engine, self._store)
            except Exception as exc:  # noqa: BLE001
                self._errors.record("transcription", exc)
            self._transcribe_stop.wait(TRANSCRIBE_POLL_SEC)

    def _speaker_loop(self) -> None:
        """Low-priority speaker labeling; never blocks recording or transcription."""
        while not self._speaker_stop.is_set():
            try:
                process_speakers_once()
            except Exception as exc:  # noqa: BLE001
                self._errors.record("speaker", exc)
            self._speaker_stop.wait(config.SPEAKER_POLL_SEC)

    # ---------- 单房间弹幕长连 ----------

    def _danmu_loop(self, rid: str, stop: threading.Event) -> None:
        def _set(status: str, connected: bool, phase: str, next_retry_ts: int = 0) -> None:
            with self._lock:
                if rid in self._rooms:
                    self._rooms[rid].status = status
                    self._rooms[rid].connected = connected
                    self._rooms[rid].phase = phase
                    self._rooms[rid].next_retry_ts = next_retry_ts

        def _backoff(base: float, jitter: float, status: str, phase: str) -> None:
            delay = base + random.uniform(0, jitter)
            _set(status, False, phase, int(time.time() + delay))
            _wait_interruptible(delay)

        def _wait_interruptible(seconds: float) -> None:
            with self._lock:
                epoch = self._control_epoch
            deadline = time.time() + seconds
            while not stop.is_set() and time.time() < deadline:
                stop.wait(min(1.0, deadline - time.time()))
                with self._lock:
                    if self._control_epoch != epoch:
                        return

        while not stop.is_set():
            was_connected = False
            try:
                cooldown = self._risk_cooldown.snapshot()
                if cooldown["active"]:
                    remaining = int(cooldown["remaining_sec"])
                    _set(
                        f"风控冷却中，约 {max(1, remaining // 60)} 分钟后重试",
                        False,
                        "risk_cooldown",
                        int(cooldown["until_ts"]),
                    )
                    _wait_interruptible(min(remaining + 1, 60))
                    continue
                refresh = browser_cookies.auto_refresh(rid)
                if refresh.get("refreshed"):
                    self.clear_risk_cooldown()
                if not refresh.get("ok"):
                    _backoff(
                        COOKIE_MISSING_BACKOFF_SEC,
                        0,
                        "自动验证未完成，等待用户验证",
                        "needs_verification",
                    )
                    continue
                fetcher = WorkerFetcher(rid, self._sink)
                if not fetcher.ttwid:
                    _backoff(
                        COOKIE_MISSING_BACKOFF_SEC,
                        0,
                        "等待用户完成信任验证",
                        "needs_verification",
                    )
                    continue
                if not fetcher.room_id:
                    if fetcher.page_state == "challenge":
                        refresh = browser_cookies.auto_refresh(rid, force=True)
                        if refresh.get("refreshed"):
                            self.clear_risk_cooldown()
                            _set("信任验证已自动恢复，准备重新连接", False, "reconnecting")
                        else:
                            self._risk_cooldown.trigger(RISK_COOLDOWN_SEC, f"房间 {rid} 命中抖音验证页")
                            cooldown = self._risk_cooldown.snapshot()
                            _set(
                                "自动验证未完成，已暂停全部房间请求",
                                False,
                                "risk_cooldown",
                                int(cooldown["until_ts"]),
                            )
                    else:
                        _backoff(
                            NOT_LIVE_BACKOFF_SEC,
                            NOT_LIVE_JITTER_SEC,
                            "暂未取得直播信息，等待后重试",
                            "waiting",
                        )
                    continue
                if not fetcher.is_live:
                    # 能取到 room_id 但 room.status≠2：主播已下播/未开播。下播后房间页仍短暂
                    # 保留 roomId，WSS 也还能握上手——若此时连了只会空挂着显"已连接"，所以这里
                    # 直接判未开播、长退避，不进 WSS。
                    _backoff(
                        NOT_LIVE_BACKOFF_SEC,
                        NOT_LIVE_JITTER_SEC,
                        "等待主播开播",
                        "waiting",
                    )
                    continue

                def _watch() -> None:
                    stop.wait()
                    try:
                        fetcher.stop()
                    except Exception:  # noqa: BLE001
                        pass

                threading.Thread(target=_watch, daemon=True).start()
                # 落主播昵称（房间页解析所得），导出时用来区分各房间，光看房间号不直观
                try:
                    self._sink.set_room_meta(rid, fetcher.anchor_nick)
                except Exception:  # noqa: BLE001
                    pass
                _set("正在监听并录音", True, "recording")
                was_connected = True
                fetcher.start()  # 阻塞直到 WS 关闭
            except Exception as e:  # noqa: BLE001
                self._errors.record(f"danmu:{rid}", e)
                _set(f"连接异常: {e!r}", False, "error")
            if not stop.is_set():
                if was_connected:
                    # 在播房间真断线：短退避快速重连
                    _backoff(
                        RECONNECT_BACKOFF_SEC,
                        RECONNECT_JITTER_SEC,
                        "直播连接中断，准备重连",
                        "reconnecting",
                    )
                else:
                    # 还没连上就失败（多半未开播/风控）：长退避
                    _backoff(
                        NOT_LIVE_BACKOFF_SEC,
                        NOT_LIVE_JITTER_SEC,
                        "连接失败，等待后重试",
                        "waiting",
                    )
        _set("已停止", False, "stopped")

    # ---------- 对外操作 ----------

    def add_room(self, rid: str, metadata: dict[str, object] | None = None) -> bool:
        rid = rid.strip()
        if not rid:
            return False
        metadata = metadata or {}
        with self._lock:
            if rid in self._rooms:
                state = self._rooms[rid]
                changed = False
                for key in ("anchor_name", "avatar_url", "source_url", "sec_user_id"):
                    value = str(metadata.get(key) or "").strip()
                    if value and getattr(state, key) != value:
                        setattr(state, key, value)
                        changed = True
                if changed:
                    self._save_rooms()
                return changed
            self._rooms[rid] = RoomState(
                rid=rid,
                anchor_name=str(metadata.get("anchor_name") or "").strip(),
                avatar_url=str(metadata.get("avatar_url") or "").strip(),
                source_url=str(metadata.get("source_url") or "").strip(),
                sec_user_id=str(metadata.get("sec_user_id") or "").strip(),
            )
        self._save_rooms()
        return True

    def remove_room(self, rid: str) -> bool:
        self.stop_room(rid)
        with self._lock:
            existed = self._rooms.pop(rid, None) is not None
        if existed:
            self._save_rooms()
        return existed

    def start_room(self, rid: str) -> bool:
        self._ensure_workers()
        with self._lock:
            st = self._rooms.get(rid)
            if st is None or st.active:
                return False
            # 同时活跃连接封顶，避免一次性铺开太多 WSS/取流入口触发风控
            active_count = sum(1 for r in self._rooms.values() if r.active)
            if active_count >= MAX_ACTIVE_ROOMS:
                st.status = f"已达并发上限({MAX_ACTIVE_ROOMS})，未启动"
                return False
            st.active = True
            st.status = "启动中"
            st.phase = "starting"
            st.next_retry_ts = 0
            st.stop = threading.Event()
            st.thread = threading.Thread(target=self._danmu_loop, args=(rid, st.stop), daemon=True)
            st.audio_thread = threading.Thread(target=self._room_audio_loop, args=(rid, st.stop), daemon=True)
            st.thread.start()
            st.audio_thread.start()
        return True

    def stop_room(self, rid: str) -> bool:
        with self._lock:
            st = self._rooms.get(rid)
            if st is None or not st.active:
                return False
            st.active = False
            if st.stop is not None:
                st.stop.set()
            st.connected = False
            st.status = "停止中"
            st.phase = "stopping"
            st.next_retry_ts = 0
        return True

    def start_all(self) -> int:
        return sum(self.start_room(rid) for rid in list(self._rooms.keys()))

    def stop_all(self) -> int:
        return sum(self.stop_room(rid) for rid in list(self._rooms.keys()))

    # ---------- 状态查询 ----------

    def _counts(self) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
        """从两个库取每房间的弹幕事件数与话术段数（personal 规模，直接 COUNT）。"""
        ev: dict[str, int] = {}
        tr: dict[str, int] = {}
        names: dict[str, str] = {}
        if config.EVENTS_DB.exists():
            try:
                c = sqlite3.connect(f"file:{config.EVENTS_DB}?mode=ro", uri=True)
                ev = {r[0]: r[1] for r in c.execute(
                    "SELECT live_id, COUNT(*) FROM events GROUP BY live_id")}
                try:
                    names = {r[0]: r[1] for r in c.execute(
                        "SELECT live_id, nickname FROM room_meta WHERE nickname IS NOT NULL")}
                except sqlite3.Error:
                    pass
                c.close()
            except sqlite3.Error:
                pass
        if config.DB_PATH.exists():
            try:
                c = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
                tr = {r[0]: r[1] for r in c.execute(
                    "SELECT room_id, COUNT(*) FROM transcripts GROUP BY room_id")}
                c.close()
            except sqlite3.Error:
                pass
        return ev, tr, names

    def status(self) -> list[dict]:
        ev, tr, names = self._counts()
        with self._lock:
            states = list(self._rooms.values())
        out = []
        for st in states:
            out.append({
                "rid": st.rid,
                "active": st.active,
                "connected": st.connected,
                "status": st.status,
                "phase": st.phase,
                "next_retry_ts": st.next_retry_ts,
                "anchor_name": st.anchor_name or names.get(st.rid, ""),
                "avatar_url": st.avatar_url,
                "source_url": st.source_url,
                "sec_user_id": st.sec_user_id,
                "events": ev.get(st.rid, 0),
                "segments": tr.get(st.rid, 0),
                "last_segment_ts": st.last_segment_ts,
            })
        return sorted(out, key=lambda x: x["rid"])

    def recent_errors(self) -> list[dict[str, object]]:
        return self._errors.snapshot()

    def risk_control_status(self) -> dict[str, object]:
        return self._risk_cooldown.snapshot()

    def clear_risk_cooldown(self) -> None:
        self._risk_cooldown.clear()
        with self._lock:
            self._control_epoch += 1

    def shutdown(self) -> None:
        self.stop_all()
        self._transcribe_stop.set()
        self._speaker_stop.set()
        if self._transcribe_thread is not None:
            self._transcribe_thread.join(timeout=5)
        if self._speaker_thread is not None:
            self._speaker_thread.join(timeout=5)
        self._store.close()
        self._sink.close()
