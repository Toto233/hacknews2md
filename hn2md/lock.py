"""Daily lock file management."""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from hn2md.constants import LOCK_STALE_SECONDS


class LockError(Exception):
    pass


def release_daily_lock(lock_path: Path, *, terminate: bool = False) -> str:
    """Release a stale lock, or explicitly terminate its owner before release.

    A live lock is never deleted in place: doing so would allow concurrent
    writers to reuse one daily ledger.
    """
    if not lock_path.exists():
        return "no_lock"
    try:
        pid_str, timestamp_str = lock_path.read_text(encoding="utf-8").strip().split("|", 1)
        pid = int(pid_str)
        age = time.time() - float(timestamp_str)
    except (OSError, ValueError):
        lock_path.unlink(missing_ok=True)
        return "malformed_lock_removed"

    if age > LOCK_STALE_SECONDS or not _pid_alive(pid):
        lock_path.unlink(missing_ok=True)
        return "stale_lock_removed"
    if not terminate:
        raise LockError(
            f"Daily run is still active (PID {pid}, age {age:.0f}s). "
            "Wait for it to finish or rerun unlock with --terminate."
        )

    _terminate_process(pid)
    deadline = time.monotonic() + 10
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _pid_alive(pid):
        raise LockError(f"Could not terminate active daily run PID {pid}; lock was kept.")
    lock_path.unlink(missing_ok=True)
    return "terminated_run_and_removed_lock"


@contextmanager
def daily_lock(lock_path: Path) -> Generator[None, None, None]:
    """Acquire a daily lock file. Raises LockError if another run is active."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while lock_path.exists():
        try:
            content = lock_path.read_text(encoding="utf-8").strip()
            pid_str, timestamp_str = content.split("|", 1)
            lock_age = time.time() - float(timestamp_str)
            if lock_age > LOCK_STALE_SECONDS:
                lock_path.unlink(missing_ok=True)
            else:
                pid = int(pid_str)
                if not _pid_alive(pid):
                    lock_path.unlink(missing_ok=True)
                else:
                    raise LockError(
                        f"Another hn2md run is active (PID {pid}, age {lock_age:.0f}s). Use --force to override."
                    )
        except (ValueError, FileNotFoundError):
            lock_path.unlink(missing_ok=True)

    try:
        descriptor = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        raise LockError("Another publishing run acquired the daily lock; try again after it finishes.") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
        lock_file.write(f"{os.getpid()}|{time.time():.0f}")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _terminate_process(pid: int) -> None:
    """Terminate one explicitly selected lock owner and its child process tree."""
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and _pid_alive(pid):
            raise LockError(f"taskkill failed for PID {pid}: {result.stderr.strip()}")
        return
    os.kill(pid, signal.SIGTERM)
