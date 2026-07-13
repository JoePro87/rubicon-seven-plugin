"""Canon distillation cache — persistent topic-keyed knowledge store.

Provides read/write/query operations for semantic learnings distilled from
canon retrievals. Backed by a JSON file with file_lock for concurrency.
"""

import json
import logging
from pathlib import Path

try:
    from hooks.hook_utils import file_lock
except ImportError:
    # Fallback for direct execution / test contexts
    from hook_utils import file_lock


SCHEMA_VERSION = 1
_EMPTY_CACHE = {"schema_version": SCHEMA_VERSION, "distillations": {}}

# Module-level parse cache: {path_str: (mtime, parsed_data)}. The distillation
# file is 2.3MB and gets parsed 2-3x per turn (prose fact-judge blob, dialogue
# claim check, Stop-hook fabrication check). Parsing once per file-change instead
# of once per read is the C25 win. Shared across DistillationCache instances that
# point at the same path; refreshed on every write so it stays coherent.
_PARSE_CACHE = {}


class DistillationCache:
    """Persistent cache of canon distillations.

    Each entry is keyed by a canonical topic_key (see hook_utils.normalize_topic_key)
    and contains a semantic learning + key facts + provenance + ingestion status.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------
    def _read_raw(self):
        """Read the full cache contents. Returns _EMPTY_CACHE on missing/corrupt file.

        Reuses a module-level parsed copy while the file's mtime is unchanged, so
        the 2.3MB JSON is parsed once per change rather than on every call. Reads
        and writes are serialized by file_lock, so returning the shared object
        (rather than a copy) is safe: writers read-modify-write under the same lock.
        """
        if not self.path.exists():
            return dict(_EMPTY_CACHE, distillations={})
        try:
            key = str(self.path)
            mtime = self.path.stat().st_mtime
            cached = _PARSE_CACHE.get(key)
            if cached is not None and cached[0] == mtime:
                return cached[1]
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "distillations" not in data:
                raise ValueError("malformed cache file")
            _PARSE_CACHE[key] = (mtime, data)
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"Distillation cache corrupted ({e}) — returning empty")
            _PARSE_CACHE.pop(str(self.path), None)
            return dict(_EMPTY_CACHE, distillations={})

    def _write_raw(self, data):
        """Atomic write of the full cache."""
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise
        # Keep the parse cache coherent with what we just wrote so the next read
        # doesn't re-parse (and can't serve pre-write data if mtime granularity
        # is coarse). Drop the entry if the stat fails for any reason.
        try:
            _PARSE_CACHE[str(self.path)] = (self.path.stat().st_mtime, data)
        except OSError:
            _PARSE_CACHE.pop(str(self.path), None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, topic_key):
        """Return the distillation entry for topic_key, or None."""
        with file_lock(lock_path=self.lock_path, timeout=5):
            data = self._read_raw()
            return data["distillations"].get(topic_key)

    def put(self, entry):
        """Insert or update an entry. Must have a 'topic_key' field."""
        if "topic_key" not in entry:
            raise ValueError("entry must have topic_key")
        with file_lock(lock_path=self.lock_path, timeout=5):
            data = self._read_raw()
            data["distillations"][entry["topic_key"]] = entry
            self._write_raw(data)

    def is_stale(self, entry, current_mtimes):
        """Return True if any source file's mtime is newer than the entry's verified_against."""
        verified = entry.get("verified_against", {})
        for source_name, current_mtime in current_mtimes.items():
            if current_mtime > verified.get(source_name, 0):
                return True
        return False

    def get_unposted(self):
        """Return all entries with ingested_at_session == None."""
        with file_lock(lock_path=self.lock_path, timeout=5):
            data = self._read_raw()
            return [
                entry for entry in data["distillations"].values()
                if entry.get("ingested_at_session") is None
            ]

    def mark_ingested(self, topic_key, session_id):
        """Set ingested_at_session for an entry.

        Logs a warning if topic_key is not in the cache (rather than silently
        no-op'ing) so typos surface immediately.
        """
        with file_lock(lock_path=self.lock_path, timeout=5):
            data = self._read_raw()
            if topic_key not in data["distillations"]:
                logging.warning(
                    f"mark_ingested: topic_key '{topic_key}' not found in cache"
                )
                return
            data["distillations"][topic_key]["ingested_at_session"] = session_id
            self._write_raw(data)

    def all_entries(self):
        """Return all entries (read-only snapshot)."""
        with file_lock(lock_path=self.lock_path, timeout=5):
            data = self._read_raw()
            return list(data["distillations"].values())
