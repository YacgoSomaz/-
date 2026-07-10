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
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import anchor_profiles, browser_cookies, config, license_manager, profile_watch
from .audio_capture import record_room_muxer
from .danmu_backend import create_fetcher, is_managed_status_backend
from .douyin_sidecar_client import SidecarStatus
from .event_sink import SqliteSink
from .sensevoice_engine import SenseVoiceEngine
from .speaker_worker import process_once as process_speakers_once
from .runtime_health import ErrorRegistry, GlobalCooldown
from .transcribe_batch import process_once
from .transcript_store import TranscriptStore

ROOMS_JSON = config.ROOMS_JSON
PENDING_JSON = config.PENDING_JSON
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
# 「录制中」必须和真有 mp3 落袋挂钩：超过此秒数没有新封口段，判为「空挂」（下播后 WSS 反复
# 重连但音频流已断），状态层据此显示为「等待开播」而非假的「录制中」，并清零录制时长。
# 段时长 SEGMENT_SEC(60s) + 转写/封口延迟，留足余量取 150s。
RECORDING_STALE_SEC = 150
# 录制看门狗：「该录却长时间没新段」的房间自动强制重连（重拉流 + 重连 WSS）。
# 这覆盖「主播在播但 mp3 不落袋」（取流卡死/电脑待机唤醒后连接已死但未察觉）。
WATCHDOG_POLL_SEC = 30           # 看门狗巡检间隔
WATCHDOG_STALE_SEC = 150         # 超过此秒没新段即判卡死，触发重连（与显示矫正阈值一致）
WATCHDOG_RESTART_COOLDOWN_SEC = 150  # 同一房间两次强制重连的最小间隔，防重连风暴


def active_room_limit() -> int:
    """Return the signed cloud policy limit, falling back to the safe default."""
    return license_manager.policy_int("max_active_rooms", MAX_ACTIVE_ROOMS, minimum=1, maximum=50)


@dataclass
class RoomState:
    """单房间运行态。线程与事件不参与序列化。"""

    rid: str
    anchor_name: str = ""
    avatar_url: str = ""
    source_url: str = ""
    sec_user_id: str = ""
    active: bool = False
    record_video: bool = False   # 是否同时录制视频（默认仅录音；按房间开关）
    status: str = "未启动"
    phase: str = "stopped"
    connected: bool = False
    next_retry_ts: int = 0
    last_segment_ts: int = 0
    added_ts: int = 0            # 添加时间（毫秒），大盘按此排序，保持添加先后顺序
    recording_since: int = 0    # 本次连续录制起始秒戳；用于显示「录了多久」，下播/断开归零
    last_restart_ts: int = 0    # 看门狗上次强制重连本房间的秒戳，用于节流，避免重连风暴
    thread: threading.Thread | None = field(default=None, repr=False)
    audio_thread: threading.Thread | None = field(default=None, repr=False)
    stop: threading.Event | None = field(default=None, repr=False)


@dataclass
class PendingAnchor:
    """待开播主播：只有 sec_user_id，后台定期探测主页，开播后抠出直播号转为正式房间。"""

    sec_user_id: str
    anchor_name: str = ""
    avatar_url: str = ""
    source_url: str = ""
    added_ts: int = 0
    last_check_ts: int = 0
    next_check_ts: int = 0   # 0 = 尽快探测（新登记/手动触发）
    last_status: str = "等待探测"


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
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self._errors = ErrorRegistry()
        self._risk_cooldown = GlobalCooldown()
        self._control_epoch = 0

        # 待开播主播：键为 sec_user_id。轮询线程懒启动（首次登记待开播时才起）。
        self._pending: dict[str, PendingAnchor] = {}
        self._pending_started = False
        self._pending_stop = threading.Event()
        self._pending_thread: threading.Thread | None = None

        self._load_rooms()
        self._load_pending()
        if self._pending:  # 重启后若有遗留待开播主播，恢复轮询
            self._start_pending_watch()

    # ---------- 房间列表持久化 ----------

    def _load_rooms(self) -> None:
        if not ROOMS_JSON.exists():
            return
        try:
            ids = json.loads(ROOMS_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for index, item in enumerate(ids, start=1):
            if isinstance(item, dict):
                rid = str(item.get("rid") or "").strip()
                if not rid:
                    continue
                cached = anchor_profiles.save_profile(rid, item)
                self._rooms[rid] = RoomState(
                    rid=rid,
                    anchor_name=cached.get("anchor_name") or str(item.get("anchor_name") or ""),
                    avatar_url=cached.get("avatar_url") or str(item.get("avatar_url") or ""),
                    source_url=cached.get("source_url") or str(item.get("source_url") or ""),
                    sec_user_id=cached.get("sec_user_id") or str(item.get("sec_user_id") or ""),
                    record_video=bool(item.get("record_video") or False),
                    # 旧库无 added_ts：按文件顺序补小序号，保持原有先后；新增的用毫秒戳，排其后。
                    added_ts=int(item.get("added_ts") or index),
                )
            else:
                rid = str(item).strip()
                if rid:
                    self._rooms[rid] = RoomState(rid=rid, added_ts=index)

    def _save_rooms(self) -> None:
        rooms = [
            {
                "rid": state.rid,
                "anchor_name": state.anchor_name,
                "avatar_url": state.avatar_url,
                "source_url": state.source_url,
                "sec_user_id": state.sec_user_id,
                "record_video": state.record_video,
                "added_ts": state.added_ts,
            }
            for state in sorted(self._rooms.values(), key=lambda room: (-room.added_ts, room.rid))
        ]
        try:
            ROOMS_JSON.write_text(json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---------- 待开播清单持久化 ----------

    def _load_pending(self) -> None:
        if not PENDING_JSON.exists():
            return
        try:
            items = json.loads(PENDING_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("sec_user_id") or "").strip()
            if not sid:
                continue
            self._pending[sid] = PendingAnchor(
                sec_user_id=sid,
                anchor_name=str(item.get("anchor_name") or ""),
                avatar_url=str(item.get("avatar_url") or ""),
                source_url=str(item.get("source_url") or ""),
                added_ts=int(item.get("added_ts") or 0),
                last_status=str(item.get("last_status") or "等待探测"),
            )

    def _save_pending(self) -> None:
        items = [
            {
                "sec_user_id": p.sec_user_id,
                "anchor_name": p.anchor_name,
                "avatar_url": p.avatar_url,
                "source_url": p.source_url,
                "added_ts": p.added_ts,
                "last_status": p.last_status,
            }
            for p in sorted(self._pending.values(), key=lambda a: a.added_ts)
        ]
        try:
            PENDING_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
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
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        """录制看门狗：定期巡检，对「该录却长时间没新段」的房间强制重连（重拉流 + 重连 WSS）。

        覆盖「主播在播但 mp3 不落袋」：取流卡死、ffmpeg 僵死、电脑待机唤醒后连接已死未察觉等。
        重连本身就是诊断信号——记到 recent_errors，让根因（卡了多久、多频繁）可见。
        """
        while not self._watchdog_stop.is_set():
            now = int(time.time())
            stale_rids: list[tuple[str, int]] = []
            with self._lock:
                for st in self._rooms.values():
                    if not (st.active and st.phase == "recording" and st.recording_since):
                        continue
                    fresh = max(st.last_segment_ts, st.recording_since)
                    age = now - fresh
                    if age > WATCHDOG_STALE_SEC and (now - st.last_restart_ts) > WATCHDOG_RESTART_COOLDOWN_SEC:
                        st.last_restart_ts = now
                        stale_rids.append((st.rid, age))
            for rid, age in stale_rids:
                if self._watchdog_stop.is_set():
                    break
                self._errors.record(
                    f"recording_stall:{rid}",
                    RuntimeError(f"在线但 {age}s 无新段，已自动重连直播间"),
                )
                # 同时打到服务器日志，便于排查根因（卡了多久、哪个房间、多频繁）
                print(f"[看门狗] 房间 {rid} 录制卡死 {age}s 无新段 → 强制重连", flush=True)
                self.restart_room(rid)
            self._watchdog_stop.wait(WATCHDOG_POLL_SEC)

    def restart_room(self, rid: str) -> bool:
        """强制重连某房间：停掉旧线程→重新拉流+连 WSS。保持在监听清单中（区别于 stop_room 的下线）。"""
        if not self.stop_room(rid):
            return False
        # 给旧线程一点时间退出（fetcher.stop() 解阻塞弹幕长连 + ffmpeg 收尾），再重启
        time.sleep(2)
        return self.start_room(rid)

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

        def _wants_video() -> bool:
            with self._lock:
                st = self._rooms.get(rid)
                return bool(st and st.record_video)

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
                    record_video=_wants_video,
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

    # ---------- 待开播主播开播探测 ----------

    def _start_pending_watch(self) -> None:
        """待开播主页探测已下线：主页 headless 探测对多数主播取不到资料、且要内置 ~300MB
        headless 浏览器。改为在播时用直播号/直播间链接添加（直播间页可靠取得资料）。
        保留 add_pending/pending_status 等接口与数据结构以兼容旧 pending_anchors.json，但不再轮询。"""
        return  # 不启动轮询线程，零浏览器活动

    def _pending_watch_loop(self) -> None:
        """串行探测到期的待开播主播；撞验证页则全局冷却，绝不并发开浏览器。"""
        while not self._pending_stop.is_set():
            if self._risk_cooldown.active():
                # 风控冷却期间不碰任何页面请求，与弹幕线一致
                self._pending_stop.wait(config.PROFILE_LOOP_TICK_SEC)
                continue
            now = int(time.time())
            with self._lock:
                due = [p.sec_user_id for p in self._pending.values() if p.next_check_ts <= now]
            for sid in due:
                if self._pending_stop.is_set() or self._risk_cooldown.active():
                    break
                self._check_one_pending(sid)
                # 两次浏览器探测之间留间隔，绝不并发
                self._pending_stop.wait(config.PROFILE_CHECK_GAP_SEC)
            self._pending_stop.wait(config.PROFILE_LOOP_TICK_SEC)

    def _check_one_pending(self, sid: str) -> None:
        """探测单个待开播主播；开播则转为正式监听房间并自动启动。"""
        import random

        with self._lock:
            if sid not in self._pending:
                return

        try:
            result = profile_watch.check_profile(
                sid,
                timeout_sec=config.PROFILE_RENDER_TIMEOUT_SEC,
                cookie_jar=browser_cookies.cached_jar(),
            )
        except Exception as exc:  # noqa: BLE001  探测异常不让轮询线崩
            self._errors.record(f"profile_watch:{sid}", exc)
            result = {"ok": False, "state": "error"}

        now = int(time.time())
        delay = config.PROFILE_POLL_SEC + random.uniform(0, config.PROFILE_POLL_JITTER_SEC)
        state = str(result.get("state") or "error")

        if state == "challenge":
            # 探测撞验证页：进全局冷却，所有线程暂停页面请求
            self._risk_cooldown.trigger(RISK_COOLDOWN_SEC, "待开播探测命中抖音验证页")

        web_id = str(result.get("web_id") or "").strip()
        if state == "live" and web_id:
            nickname = str(result.get("nickname") or "").strip()
            promoted = self._promote_pending(sid, web_id, nickname)
            if promoted:
                return  # 已转正并从待开播移除

        nickname = str(result.get("nickname") or "").strip()
        with self._lock:
            p = self._pending.get(sid)
            if p is None:
                return
            # 离线探测也能拿到昵称——补上空白昵称，待开播列表立刻有名字可显示
            if nickname and not p.anchor_name:
                p.anchor_name = nickname
            p.last_check_ts = now
            p.next_check_ts = int(now + delay)
            p.last_status = {
                "live": "已开播，正在转入监听",
                "offline": "未开播，持续监测中",
                "challenge": "探测遇验证页，稍后重试",
                "error": "探测失败，稍后重试",
            }.get(state, "监测中")
            self._save_pending()

    def _promote_pending(self, sid: str, web_id: str, nickname: str) -> bool:
        """待开播主播开播：登记为正式房间、自动启动、移出待开播清单。"""
        with self._lock:
            p = self._pending.get(sid)
            if p is None:
                return False
            meta = {
                "anchor_name": nickname or p.anchor_name,
                "avatar_url": p.avatar_url,
                "source_url": p.source_url or f"https://live.douyin.com/{web_id}",
                "sec_user_id": sid,
            }
        # add_room / start_room 自带锁，必须在锁外调用
        self.add_room(web_id, meta)
        self.start_room(web_id)
        with self._lock:
            self._pending.pop(sid, None)
            self._save_pending()
        return True

    # ---------- 单房间弹幕长连 ----------

    def _danmu_loop(self, rid: str, stop: threading.Event) -> None:
        def _set(status: str, connected: bool, phase: str, next_retry_ts: int = 0) -> None:
            with self._lock:
                st = self._rooms.get(rid)
                if st is not None:
                    st.status = status
                    st.connected = connected
                    st.phase = phase
                    st.next_retry_ts = next_retry_ts
                    # 录制时长：进入 recording 时起表（跨短暂 reconnecting 不重置）；其余状态归零。
                    if phase == "recording":
                        if st.recording_since == 0:
                            st.recording_since = int(time.time())
                    elif phase != "reconnecting":
                        st.recording_since = 0

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

        def _update_metadata(nick: str, avatar: str) -> None:
            nick = (nick or "").strip()
            avatar = (avatar or "").strip()
            if not nick and not avatar:
                return
            changed = False
            with self._lock:
                st = self._rooms.get(rid)
                if st is not None:
                    if nick and st.anchor_name != nick:
                        st.anchor_name = nick
                        changed = True
                    if avatar and st.avatar_url != avatar:
                        st.avatar_url = avatar
                        changed = True
            if changed:
                self._save_rooms()

        def _sidecar_status(status: SidecarStatus) -> None:
            if status.live is True:
                _set("正在监听并录音", True, "recording")
                return
            if status.ended:
                _set(
                    f"主播已下播，{status.retry_interval_seconds or 60} 秒后继续观察",
                    False,
                    "waiting",
                    int(time.time() + float(status.retry_interval_seconds or NOT_LIVE_BACKOFF_SEC)),
                )
                return
            _set(
                status.message or "等待主播开播",
                False,
                "waiting",
                int(time.time() + float(status.retry_interval_seconds or NOT_LIVE_BACKOFF_SEC)),
            )

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
                if is_managed_status_backend():
                    fetcher = create_fetcher(
                        rid,
                        self._sink,
                        on_status=_sidecar_status,
                        on_metadata=_update_metadata,
                    )

                    def _watch_sidecar() -> None:
                        stop.wait()
                        try:
                            fetcher.stop()
                        except Exception:  # noqa: BLE001
                            pass

                    threading.Thread(target=_watch_sidecar, daemon=True).start()
                    _set("正在连接本地弹幕服务", False, "waiting")
                    fetcher.start()  # sidecar 自己处理未开播轮询与 WSS 重连
                    was_connected = fetcher.is_live
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
                fetcher = create_fetcher(rid, self._sink)
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
                # 开播自动取资料：直播间页（fetcher 已抓）可靠取得昵称+头像，回写房间状态与 room_meta。
                # 这解决了主页 headless 探测拿不到资料的问题——开播后直播间页是可靠数据源。
                try:
                    self._sink.set_room_meta(rid, fetcher.anchor_nick)
                except Exception:  # noqa: BLE001
                    pass
                _update_metadata(fetcher.anchor_nick, fetcher.anchor_avatar)
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
        cached_metadata = anchor_profiles.save_profile(rid, metadata)
        with self._lock:
            if rid in self._rooms:
                state = self._rooms[rid]
                changed = False
                merged = {**metadata, **{k: v for k, v in cached_metadata.items() if v}}
                for key in ("anchor_name", "avatar_url", "source_url", "sec_user_id"):
                    value = str(merged.get(key) or "").strip()
                    if value and getattr(state, key) != value:
                        setattr(state, key, value)
                        changed = True
                if changed:
                    self._save_rooms()
                return changed
            self._rooms[rid] = RoomState(
                rid=rid,
                anchor_name=str(cached_metadata.get("anchor_name") or metadata.get("anchor_name") or "").strip(),
                avatar_url=str(cached_metadata.get("avatar_url") or metadata.get("avatar_url") or "").strip(),
                source_url=str(cached_metadata.get("source_url") or metadata.get("source_url") or "").strip(),
                sec_user_id=str(cached_metadata.get("sec_user_id") or metadata.get("sec_user_id") or "").strip(),
                added_ts=int(time.time() * 1000),  # 毫秒戳：大盘按添加先后排序
            )
        self._save_rooms()
        return True

    def update_room_profile(self, rid: str, metadata: dict[str, object] | None = None) -> bool:
        """Update display metadata for an already configured room only.

        Historical pages can refresh cached avatars without silently re-adding a
        room the user removed from the listening list.
        """
        rid = rid.strip()
        if not rid:
            return False
        cached_metadata = anchor_profiles.save_profile(rid, metadata or {})
        with self._lock:
            state = self._rooms.get(rid)
            if state is None:
                return False
            changed = False
            for key in ("anchor_name", "avatar_url", "source_url", "sec_user_id"):
                value = str(cached_metadata.get(key) or "").strip()
                if value and getattr(state, key) != value:
                    setattr(state, key, value)
                    changed = True
            if changed:
                self._save_rooms()
            return changed

    def set_record_video(self, rid: str, enabled: bool) -> bool:
        """切换房间是否录制视频。录制循环每次取流重启时实时读取，故下次重连即生效；
        想立即生效可停止再启动该房间（强制 record_room_muxer 重新进入）。"""
        rid = rid.strip()
        with self._lock:
            st = self._rooms.get(rid)
            if st is None or st.record_video == bool(enabled):
                changed = False
            else:
                st.record_video = bool(enabled)
                changed = True
        if changed:
            self._save_rooms()
        return changed

    # ---------- 待开播主播对外操作 ----------

    def add_pending(self, sec_user_id: str, metadata: dict[str, object] | None = None) -> dict[str, object]:
        """登记一个待开播主播（只有 sec_user_id）。返回 {ok, reason}。"""
        sid = (sec_user_id or "").strip()
        if not sid:
            return {"ok": False, "reason": "缺少 sec_user_id"}
        metadata = metadata or {}
        with self._lock:
            if sid in self._pending:
                return {"ok": False, "reason": "该主播已在待开播清单中"}
            if len(self._pending) >= config.MAX_PENDING_ANCHORS:
                return {"ok": False, "reason": f"待开播主播已达上限（{config.MAX_PENDING_ANCHORS}）"}
            self._pending[sid] = PendingAnchor(
                sec_user_id=sid,
                anchor_name=str(metadata.get("anchor_name") or "").strip(),
                avatar_url=str(metadata.get("avatar_url") or "").strip(),
                source_url=str(metadata.get("source_url") or "").strip(),
                added_ts=int(time.time()),
                next_check_ts=0,  # 尽快做第一次探测
                last_status="等待探测",
            )
            self._save_pending()
        self._start_pending_watch()
        return {"ok": True}

    def remove_pending(self, sec_user_id: str) -> bool:
        sid = (sec_user_id or "").strip()
        with self._lock:
            existed = self._pending.pop(sid, None) is not None
            if existed:
                self._save_pending()
        return existed

    def pending_status(self) -> list[dict[str, object]]:
        with self._lock:
            items = list(self._pending.values())
        return [
            {
                "sec_user_id": p.sec_user_id,
                "anchor_name": p.anchor_name,
                "avatar_url": p.avatar_url,
                "source_url": p.source_url,
                "added_ts": p.added_ts,
                "last_check_ts": p.last_check_ts,
                "status": p.last_status,
            }
            for p in sorted(items, key=lambda a: a.added_ts)
        ]

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
            limit = active_room_limit()
            if active_count >= limit:
                st.status = f"已达授权并发上限({limit})，未启动"
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

    def clear_all_data(self) -> dict[str, object]:
        """一键清除所有录制数据：停止全部录制 → 清空库 → 删 audio/video/exports。

        保留：主播列表、登录 cookie、待开播、模型、各项设置。库文件保留只删行（避免文件锁），
        目录整删后重建。正在写的极个别 ffmpeg 段文件若被占用会跳过，不影响整体清除。
        """
        self.stop_all()
        time.sleep(2)  # 等录音线/ffmpeg 退出，释放 audio 文件占用
        # 1) 清库（用管理器自己持有的连接，绕开文件锁）
        try:
            self._sink.clear_all()
        except Exception as exc:  # noqa: BLE001
            self._errors.record("clear_all:events", exc)
        try:
            self._store.clear_all()
        except Exception as exc:  # noqa: BLE001
            self._errors.record("clear_all:transcripts", exc)
        # 声纹标签库（独立文件，未被长期占用）：直接删表行或删文件
        for db in (config.SPEAKER_DB_PATH,):
            try:
                if db.exists():
                    c = sqlite3.connect(str(db))
                    for t in ("speaker_labels", "speaker_profiles"):
                        try:
                            c.execute(f"DELETE FROM {t}")
                        except sqlite3.Error:
                            pass
                    c.commit(); c.close()
            except sqlite3.Error:
                pass
        # 2) 删录制目录（audio/video/exports），随后重建空目录
        removed = 0
        for d in (config.AUDIO_DIR, config.VIDEO_DIR, config.EXPORT_DIR):
            if d.exists():
                before = sum(1 for _ in d.rglob("*") if _.is_file())
                shutil.rmtree(d, ignore_errors=True)
                removed += before
        config.ensure_dirs()
        # 3) 复位每房间录制态（时长/段时间戳归零）
        with self._lock:
            for st in self._rooms.values():
                st.last_segment_ts = 0
                st.recording_since = 0
                st.last_restart_ts = 0
        return {"ok": True, "removed_files": removed}

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
        now = int(time.time())
        with self._lock:
            states = list(self._rooms.values())
        out = []
        for st in states:
            phase = st.phase
            recording_since = st.recording_since
            status_text = st.status
            connected = st.connected
            # 空挂检测：自称 recording 但长时间没有新封口段（下播后 WSS 空连）→ 矫正为「等待开播」，
            # 清零录制时长。判活基准取「最近封口段」与「本次录制起点」的较晚者（覆盖刚开始还没出首段）。
            if phase == "recording" and recording_since:
                fresh = max(st.last_segment_ts, st.recording_since)
                if now - fresh > RECORDING_STALE_SEC:
                    phase = "waiting"
                    status_text = "录制中断/疑似下播，等待恢复"
                    recording_since = 0
                    connected = False
            out.append({
                "rid": st.rid,
                "active": st.active,
                "record_video": st.record_video,
                "connected": connected,
                "status": status_text,
                "phase": phase,
                "next_retry_ts": st.next_retry_ts,
                "anchor_name": st.anchor_name or names.get(st.rid, ""),
                "avatar_url": st.avatar_url,
                "source_url": st.source_url,
                "sec_user_id": st.sec_user_id,
                "events": ev.get(st.rid, 0),
                "segments": tr.get(st.rid, 0),
                "last_segment_ts": st.last_segment_ts,
                "added_ts": st.added_ts,
                "recording_since": recording_since,
            })
        # 新添加/最新登记的主播优先展示，减少刚添加后还要滚到列表底部寻找。
        return sorted(out, key=lambda x: (-x["added_ts"], x["rid"]))

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
        self._pending_stop.set()
        self._watchdog_stop.set()
        if self._transcribe_thread is not None:
            self._transcribe_thread.join(timeout=5)
        if self._speaker_thread is not None:
            self._speaker_thread.join(timeout=5)
        if self._pending_thread is not None:
            self._pending_thread.join(timeout=5)
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5)
        self._store.close()
        self._sink.close()
