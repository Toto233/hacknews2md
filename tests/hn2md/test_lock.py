"""Tests for hn2md.lock -- daily lock file mechanism."""

import os
import time

import pytest

from hn2md.lock import LockError, _pid_alive, daily_lock


def test_lock_creates_file(tmp_path):
    """Lock file should be created when entering the context manager."""
    lock_path = tmp_path / ".lock"
    with daily_lock(lock_path):
        assert lock_path.exists()


def test_lock_cleans_up_after(tmp_path):
    """Lock file should be removed when exiting the context manager."""
    lock_path = tmp_path / ".lock"
    with daily_lock(lock_path):
        pass
    assert not lock_path.exists()


def test_lock_contains_pid_and_timestamp(tmp_path):
    """Lock file content should be 'PID|timestamp'."""
    lock_path = tmp_path / ".lock"
    with daily_lock(lock_path):
        content = lock_path.read_text(encoding="utf-8").strip()
        pid_str, ts_str = content.split("|", 1)
        assert int(pid_str) == os.getpid()
        # Timestamp should be a reasonable epoch value
        ts = float(ts_str)
        assert ts > 1_000_000_000  # after ~2001


def test_lock_raises_on_active_process(tmp_path):
    """A non-stale lock held by a live PID should raise LockError."""
    lock_path = tmp_path / ".lock"
    # Write a lock with our own PID and a recent timestamp
    lock_path.write_text(f"{os.getpid()}|{time.time():.0f}", encoding="utf-8")
    try:
        with daily_lock(lock_path):
            raise AssertionError("Should not reach here")
    except LockError as e:
        assert "active" in str(e).lower() or "hn2md" in str(e).lower()


def test_lock_stale_recovery(tmp_path):
    """A stale lock (old timestamp) should be overridden successfully."""
    from hn2md.constants import LOCK_STALE_SECONDS

    lock_path = tmp_path / ".lock"
    # Write a lock with a very old timestamp (well beyond stale threshold)
    old_ts = time.time() - LOCK_STALE_SECONDS - 3600
    lock_path.write_text(f"99999|{old_ts:.0f}", encoding="utf-8")
    with daily_lock(lock_path):
        assert True  # acquired successfully


def test_lock_dead_pid_recovery(tmp_path):
    """A lock held by a dead PID should be overridden successfully."""
    lock_path = tmp_path / ".lock"
    # PID 0 is never a real process on Windows/Linux
    lock_path.write_text(f"0|{time.time():.0f}", encoding="utf-8")
    with daily_lock(lock_path):
        assert True  # acquired successfully


@pytest.mark.parametrize("pid", [0, -1])
def test_pid_alive_rejects_nonpositive_pid(pid):
    """Nonpositive values are process selectors on Unix, not valid lock PIDs."""
    assert _pid_alive(pid) is False


def test_lock_cleans_up_on_exception(tmp_path):
    """Lock file should be cleaned up even when the body raises."""
    lock_path = tmp_path / ".lock"
    try:
        with daily_lock(lock_path):
            raise ValueError("boom")
    except ValueError:
        pass
    assert not lock_path.exists()


def test_lock_creates_parent_directory(tmp_path):
    """Lock should create parent directories if they don't exist."""
    lock_path = tmp_path / "sub" / "dir" / ".lock"
    assert not lock_path.parent.exists()
    with daily_lock(lock_path):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_lock_malformed_content_recovery(tmp_path):
    """A lock file with garbage content should be silently replaced."""
    lock_path = tmp_path / ".lock"
    lock_path.write_text("not-a-valid-lock", encoding="utf-8")
    with daily_lock(lock_path):
        # Should have replaced the bad content
        content = lock_path.read_text(encoding="utf-8").strip()
        pid_str, ts_str = content.split("|", 1)
        assert int(pid_str) == os.getpid()
