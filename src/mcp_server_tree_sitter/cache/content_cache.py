"""Shared content-addressed cache for derived analysis results.

Results live under ``$XDG_CACHE_HOME/tree-sitter-mcp/v1`` (or
``~/.cache/tree-sitter-mcp/v1``), sharded by the first byte of the key.
The key covers the schema, the language-pack version, the language, the
operation, the caller's identity string, and the file bytes. The path is
not part of the key. Writes land in a temporary file in the same shard and
then rename into place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import APP_DIR_NAME

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TOUCH_INTERVAL_SECONDS = 3600
TRIM_INTERVAL_SECONDS = 86400
TRIM_MAX_AGE_SECONDS = 5 * 86400
STALE_LOCK_SECONDS = 3600
NOTE_LIMIT = 16384

_pack_version: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pack_version() -> str:
    """Return the installed tree-sitter-language-pack version."""
    global _pack_version
    if _pack_version is None:
        try:
            from importlib.metadata import version

            _pack_version = version("tree-sitter-language-pack")
        except Exception:
            _pack_version = "unknown"
    return _pack_version


def default_cache_dir() -> Path:
    """Directory that holds the shared cache when none is configured."""
    env_dir = os.environ.get("MCP_TS_CACHE_DIR")
    if env_dir:
        return Path(env_dir)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / APP_DIR_NAME


class ContentCache:
    """Process-local stat notes plus a shared directory of derived results."""

    def __init__(self, root: Path | None = None, enabled: bool = True) -> None:
        """Keep ``root`` when the caller already chose a directory.

        ``None`` resolves the directory on first use, from configuration,
        ``MCP_TS_CACHE_DIR``, or the XDG cache home. ``enabled`` is this
        process's own switch and starts from the config value.
        """
        self._root = root
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        self.content_reads = 0
        self._notes: dict[str, tuple[int, int, str]] = {}
        self._lock = threading.Lock()
        self._trim_checked_at = 0.0

    def set_enabled(self, enabled: bool) -> None:
        """Turn this process's use of the disk cache on or off."""
        self.enabled = enabled

    def invalidate(self, file_path: Path | str | None = None) -> None:
        """Drop stat notes. A full clear also deletes shared result files.

        A path drops that file's note and leaves result files in place. Those
        files are named by content, and there is no path index. No path drops
        every note and every result file. Trim bookkeeping stays.
        """
        with self._lock:
            if file_path is None:
                self._notes.clear()
            else:
                self._notes.pop(os.path.realpath(file_path), None)
        if file_path is None:
            self._delete_results()

    def get(
        self,
        file_path: Path,
        operation: str,
        language: str,
        identity: str,
        source_bytes: bytes | None = None,
    ) -> Any | None:
        """Return a stored result for these bytes, or None on a miss.

        A path lookup hashes the file at ``file_path``. Passing ``source_bytes``
        hashes those bytes and does not stat or read the path.
        """
        if not self._allowed():
            return None
        self.maybe_trim()
        try:
            if source_bytes is None:
                content_hash = self._content_hash(Path(file_path))
            else:
                content_hash = _sha256(source_bytes)
            key = self._cache_key(operation, language, identity, content_hash)
            entry = self._entry_path(key)
            text = entry.read_text(encoding="utf-8")
            value = json.loads(text)
        except FileNotFoundError:
            self.misses += 1
            return None
        except (OSError, json.JSONDecodeError, UnicodeError):
            self.misses += 1
            return None
        if not isinstance(value, dict):
            self.misses += 1
            return None
        self._touch(entry)
        self.hits += 1
        return value

    def put(self, source_bytes: bytes, operation: str, language: str, identity: str, value: Any) -> None:
        """Store a JSON result for these bytes. A failure leaves the caller result intact.

        The key is the hash of ``source_bytes``. This does not open a path and does
        not update the stat note.
        """
        if not self._allowed():
            return
        try:
            payload = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            logger.debug("content cache skipped an unserializable %s result", operation)
            return
        try:
            self.maybe_trim()
            content_hash = _sha256(source_bytes)
            key = self._cache_key(operation, language, identity, content_hash)
            self._write_atomic(key, payload)
        except OSError:
            logger.debug("content cache store failed for %s", operation, exc_info=True)

    def maybe_trim(self) -> None:
        """Drop unused result files about once a day.

        A result is unused when its mtime is older than five days. Readers
        refresh that mtime, at most once an hour. A lock file keeps every
        process from scanning at once.
        """
        now = time.time()
        with self._lock:
            if now - self._trim_checked_at < TOUCH_INTERVAL_SECONDS:
                return
            self._trim_checked_at = now
        try:
            version = self._version_dir()
            version.mkdir(parents=True, exist_ok=True)
            stamp = version / "trim.txt"
            try:
                last = float(stamp.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                last = 0.0
            if now - last < TRIM_INTERVAL_SECONDS:
                return
            self._trim(version, now)
        except OSError:
            logger.debug("content cache trim failed", exc_info=True)

    def _allowed(self) -> bool:
        if not self.enabled:
            return False
        try:
            from ..di import get_container

            return bool(get_container().get_config().cache.enabled)
        except (ImportError, AttributeError):
            return True

    def _resolve_root(self) -> Path:
        if self._root is not None:
            return self._root
        try:
            from ..di import get_container

            configured = get_container().get_config().cache.directory
        except (ImportError, AttributeError):
            configured = None
        if configured:
            return Path(configured)
        return default_cache_dir()

    def _version_dir(self) -> Path:
        return self._resolve_root() / "v1"

    def _cache_key(self, operation: str, language: str, identity: str, content_hash: str) -> str:
        material = "\0".join(
            (
                str(SCHEMA_VERSION),
                pack_version(),
                operation,
                language,
                identity,
                content_hash,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _entry_path(self, key: str) -> Path:
        return self._version_dir() / key[:2] / key

    def _content_hash(self, file_path: Path) -> str:
        real = os.path.realpath(file_path)
        st = os.stat(real)
        with self._lock:
            note = self._notes.get(real)
            if note is not None and note[0] == st.st_mtime_ns and note[1] == st.st_size:
                self._notes.pop(real)
                self._notes[real] = note
                return note[2]
        with open(real, "rb") as handle:
            data = handle.read()
        with self._lock:
            self.content_reads += 1
        digest = hashlib.sha256(data).hexdigest()
        st_after = os.stat(real)
        if st.st_mtime_ns == st_after.st_mtime_ns and st.st_size == st_after.st_size == len(data):
            with self._lock:
                self._remember_note(real, st_after.st_mtime_ns, st_after.st_size, digest)
        return digest

    def _remember_note(self, real: str, mtime_ns: int, size: int, digest: str) -> None:
        """Record a stat note and drop the oldest notes past ``NOTE_LIMIT``.

        The caller holds ``self._lock``.
        """
        self._notes.pop(real, None)
        self._notes[real] = (mtime_ns, size, digest)
        while len(self._notes) > NOTE_LIMIT:
            del self._notes[next(iter(self._notes))]

    def _delete_results(self) -> None:
        """Remove result files. Trim bookkeeping and in-progress temp files stay."""
        try:
            version = self._version_dir()
            if not version.is_dir():
                return
            for shard in list(version.iterdir()):
                if not shard.is_dir() or len(shard.name) != 2:
                    continue
                for entry in list(shard.iterdir()):
                    if not entry.is_file() or entry.name.startswith(".") or len(entry.name) != 64:
                        continue
                    try:
                        entry.unlink()
                    except OSError:
                        continue
                try:
                    shard.rmdir()
                except OSError:
                    pass
        except OSError:
            logger.debug("content cache clear failed", exc_info=True)

    def _write_atomic(self, key: str, payload: str) -> None:
        destination = self._entry_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{key}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _touch(self, entry: Path) -> None:
        try:
            modified = entry.stat().st_mtime
        except OSError:
            return
        if time.time() - modified < TOUCH_INTERVAL_SECONDS:
            return
        try:
            os.utime(entry, None)
        except OSError:
            return

    def _trim(self, version: Path, now: float) -> None:
        lock_path = version / "trim.lock"
        try:
            if lock_path.exists() and now - lock_path.stat().st_mtime > STALE_LOCK_SECONDS:
                lock_path.unlink()
        except OSError:
            return
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return
        except OSError:
            return
        removed = 0
        try:
            cutoff = now - TRIM_MAX_AGE_SECONDS
            for shard in version.iterdir():
                if not shard.is_dir() or len(shard.name) != 2:
                    continue
                for entry in shard.iterdir():
                    if not entry.is_file() or entry.name.startswith(".") or len(entry.name) != 64:
                        continue
                    try:
                        if entry.stat().st_mtime < cutoff:
                            entry.unlink()
                            removed += 1
                    except OSError:
                        continue
                try:
                    shard.rmdir()
                except OSError:
                    pass
            temporary = version / f".trim.{os.getpid()}.tmp"
            temporary.write_text(str(int(now)), encoding="utf-8")
            os.replace(temporary, version / "trim.txt")
        finally:
            os.close(fd)
            try:
                lock_path.unlink()
            except OSError:
                pass
        if removed:
            logger.info("content cache trim removed %s unused files", removed)
