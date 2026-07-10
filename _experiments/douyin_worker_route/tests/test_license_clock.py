from pipeline import license_clock


def test_clock_guard_records_latest_time_and_rejects_large_rollback(tmp_path):
    state_path = tmp_path / "clock.json"

    first = license_clock.check_and_record(now=1_000, path=state_path)
    forward = license_clock.check_and_record(now=1_200, path=state_path)
    small_adjustment = license_clock.check_and_record(now=950, path=state_path)
    rollback = license_clock.check_and_record(now=800, path=state_path)

    assert first.ok is True
    assert forward.ok is True
    assert small_adjustment.ok is True
    assert rollback.ok is False
    assert "系统时间异常" in rollback.reason
    assert license_clock.last_seen_at(path=state_path) == 1_200
