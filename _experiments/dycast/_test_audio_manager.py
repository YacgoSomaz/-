"""用伪取流/伪录制/伪转写验证 AudioManager 状态机，不依赖真实 Whisper/网络。"""

import asyncio
import os
from pathlib import Path

import audio_manager as am

TRACE = Path("_audio_mgr_trace.txt")


def trace(msg: str):
    TRACE.write_text(msg, encoding="utf-8")


class FakeProc:
    """伪 ffmpeg：定时往 out_dir 写 chunk 文件，然后退出。"""

    def __init__(self, out_dir: str, n: int = 100, interval: float = 0.05):
        self.returncode = None
        # 持续产生切片，直到被 terminate（模拟一直在直播）
        self._task = asyncio.create_task(self._gen(out_dir, n, interval))

    async def _gen(self, out_dir, n, interval):
        try:
            for i in range(n):
                await asyncio.sleep(interval)
                Path(out_dir, f"chunk_{i:05d}.wav").write_bytes(b"x")
        except asyncio.CancelledError:
            pass

    def terminate(self):
        self.returncode = -1
        self._task.cancel()

    def kill(self):
        self.terminate()

    async def wait(self):
        await asyncio.shield(self._task)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


async def fake_get_stream_url(live_url, timeout_sec: int = 8):
    return "fake://stream"


async def fake_start_segment_recorder(stream_url, out_pattern, segment_sec, stderr_path=None):
    return FakeProc(os.path.dirname(out_pattern))


def fake_transcribe_file(wav_path, model_name="tiny"):
    idx = int(Path(wav_path).stem.split("_")[-1])
    return f"伪话术段{idx}"


async def main():
    trace("patching")
    am.get_stream_url = fake_get_stream_url
    am.start_segment_recorder = fake_start_segment_recorder
    am.transcribe_file = fake_transcribe_file

    saved: list[tuple] = []

    def save_cb(room_num, text, start_sec, ts):
        saved.append((room_num, text, start_sec))
        return True

    trace("creating manager")
    mgr = am.AudioManager(
        save_cb, enabled=True, max_rooms=2, model="tiny", segment_sec=15
    )

    trace("starting rooms")
    # 两个房间并发
    mgr.start_room("roomA")
    mgr.start_room("roomB")
    # 重复 start 不应重复起任务
    mgr.start_room("roomA")

    # 等到两个房间各至少 3 段，超时则失败，避免测试挂死。
    for _ in range(100):
        a = sum(1 for s in saved if s[0] == "roomA")
        b = sum(1 for s in saved if s[0] == "roomB")
        trace(f"waiting initial a={a} b={b}")
        if a >= 3 and b >= 3:
            break
        await asyncio.sleep(0.1)
    else:
        Path("_audio_mgr_check.txt").write_text("RESULT: FAIL\nreason: timeout waiting for initial segments", encoding="utf-8")
        print("FAIL")
        return

    trace("stopping rooms")
    mgr.stop_room("roomA")
    mgr.stop_room("roomB")
    trace("shutdown")
    await asyncio.wait_for(mgr.shutdown(), timeout=5)
    c_stop = len(saved)
    tasks_alive = [t.get_name() for t in asyncio.all_tasks() if not t.done()
                   and t is not asyncio.current_task()]

    # 停止后确认落库"停止增长"（验证 ffmpeg+consumer 被终止，不再有幽灵转写）。
    await asyncio.sleep(0.6)
    c2 = len(saved)
    await asyncio.sleep(0.6)
    c3 = len(saved)
    no_leak = c_stop == c2 == c3  # shutdown 返回后绝对不应再增长
    import sys as _sys
    print(f"DBG c_stop={c_stop} c2={c2} c3={c3} alive={tasks_alive}", file=_sys.stderr)

    a_rows = [s for s in saved if s[0] == "roomA"]
    b_rows = [s for s in saved if s[0] == "roomB"]
    out = []
    out.append(f"roomA 段数={len(a_rows)} 样例={a_rows[:2]}")
    out.append(f"roomB 段数={len(b_rows)} 样例={b_rows[:2]}")
    # start_sec 应为 idx*segment_sec
    ok_sec = all(text.endswith(str(sec // 15)) for (_r, text, sec) in saved)
    out.append(f"start_sec 计算正确: {ok_sec}")
    out.append(f"任务已全部清理: {len(mgr._tasks) == 0}")
    out.append(f"停止后无幽灵落库(无泄漏): {no_leak}")
    passed = len(a_rows) >= 3 and len(b_rows) >= 3 and ok_sec and len(mgr._tasks) == 0 and no_leak
    out.append(f"RESULT: {'PASS' if passed else 'FAIL'}")
    Path("_audio_mgr_check.txt").write_text("\n".join(out), encoding="utf-8")
    trace("done")
    print("PASS" if passed else "FAIL")


if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=12))
    except Exception as exc:
        Path("_audio_mgr_check.txt").write_text(f"RESULT: FAIL\nreason: {type(exc).__name__}: {exc}", encoding="utf-8")
        print("FAIL")
