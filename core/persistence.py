"""Durable local ledger operations shared by foreground and scheduled writers."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()
_local = threading.local()

_jsonl_cache: dict[str, tuple[int, int, list[dict]]] = {}
_cache_guard = threading.Lock()


def clear_jsonl_cache(path: Path | None = None) -> None:
    """Clear memory cache for a specific file or all files."""
    with _cache_guard:
        if path is not None:
            _jsonl_cache.pop(str(Path(path).resolve()), None)
        else:
            _jsonl_cache.clear()


@contextmanager
def file_lock(path: Path):
    """A reentrant thread lock plus a cooperating cross-process file lock."""
    path = Path(path).resolve()
    key = str(path)
    with _guard:
        mutex = _locks.setdefault(key, threading.RLock())
    with mutex:
        held = getattr(_local, 'held', set())
        if key in held:
            yield
            return
        lock_path = path.with_suffix(path.suffix + '.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if not stream.tell():
                    stream.write(b'\0'); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            _local.held = held | {key}
            try:
                yield
            finally:
                _local.held = held
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_write_bytes(path: Path, payload: bytes):
    """Flush a sibling temporary file before replacing; preserve old bytes on failure."""
    path = Path(path)
    key = str(path.resolve())
    with _cache_guard:
        _jsonl_cache.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.atomic-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            pass


def append_jsonl(path: Path, record: dict):
    """Return only after a locked, fsynced append; propagate persistence failures."""
    path = Path(path)
    key = str(path.resolve())
    with _cache_guard:
        _jsonl_cache.pop(key, None)
    payload = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    with file_lock(path):
        with path.open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            previous_size = stream.tell()
            if previous_size:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b'\n':
                    raise ValueError(f'Incomplete ledger tail requires recovery: {path}')
            try:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            except Exception:
                stream.truncate(previous_size)
                stream.flush()
                raise


def read_jsonl(path: Path) -> list[dict]:
    resolved = Path(path).resolve()
    key = str(resolved)
    with file_lock(resolved):
        if not resolved.exists():
            with _cache_guard:
                _jsonl_cache.pop(key, None)
            return []
        
        stat = resolved.stat()
        mtime_ns = stat.st_mtime_ns
        size = stat.st_size
        with _cache_guard:
            cached = _jsonl_cache.get(key)
            if cached is not None and cached[0] == mtime_ns and cached[1] == size:
                return [r.copy() for r in cached[2]]

        rows = []
        for number, line in enumerate(resolved.read_text(encoding='utf-8').splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('Expected JSON object')
            except ValueError as exc:
                raise ValueError(f'Invalid ledger record {resolved}:{number}: {exc}') from exc
            rows.append(row)

        with _cache_guard:
            _jsonl_cache[key] = (mtime_ns, size, rows)

        return [r.copy() for r in rows]
