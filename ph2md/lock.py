"""Kernel backed source/month writer lock, released when its owner exits."""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


_local = threading.local()


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Product Hunt already has an active writer: {path.name}") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def source_lock(root: Path) -> Iterator[None]:
    """Serialize all PH state writes, including migration and schema setup."""
    path = (root / "data" / "producthunt" / "locks" / "source.lock").resolve()
    held = getattr(_local, "held", set())
    if path in held:
        yield
        return
    with _file_lock(path):
        _local.held = held | {path}
        try:
            yield
        finally:
            _local.held = held


@contextmanager
def monthly_lock(root: Path, year: int, month: int) -> Iterator[None]:
    with source_lock(root):
        with _file_lock(root / "data" / "producthunt" / "locks" / f"{year}{month:02d}.lock"):
            yield
