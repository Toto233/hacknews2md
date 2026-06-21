"""Daily lock file management."""

import os
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from hn2md.constants import LOCK_STALE_SECONDS


class LockError(Exception):
    pass


@contextmanager
def daily_lock(lock_path: Path) -> Generator[None, None, None]:
    """Acquire a daily lock file. Raises LockError if another run is active."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
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

    lock_path.write_text(f"{os.getpid()}|{time.time():.0f}", encoding="utf-8")
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
