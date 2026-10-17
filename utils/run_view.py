"""Per-browser-session immutable artifact and incremental event caches."""

import sys
from collections import OrderedDict


def _size_bytes(value):
    pending, seen, total = [value], set(), 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return total


class RunViewCache:
    def __init__(self, capacity=128, max_bytes=64 * 1024 * 1024):
        if any(type(value) is not int or value < 1 for value in (capacity, max_bytes)):
            raise ValueError("Run view cache limits must be positive integers")
        self.capacity = capacity
        self.max_bytes = max_bytes
        self.cached_bytes = 0
        self.snapshots = {}
        self.artifacts = {}
        self.events = {}
        self._sizes = OrderedDict()

    def _discard(self, kind, key):
        getattr(self, kind).pop(key, None)
        self.cached_bytes -= self._sizes.pop((kind, key), 0)

    def _cached(self, kind, key):
        cache = getattr(self, kind)
        if key not in cache:
            return None
        value = cache.pop(key)
        cache[key] = value
        self._sizes.move_to_end((kind, key))
        return value

    def _save(self, kind, key, value):
        self._discard(kind, key)
        size = _size_bytes((key, value))
        if size > self.max_bytes:
            return value
        cache = getattr(self, kind)
        cache[key] = value
        self._sizes[(kind, key)] = size
        self.cached_bytes += size
        while len(cache) > self.capacity:
            self._discard(kind, next(iter(cache)))
        while self.cached_bytes > self.max_bytes:
            self._discard(*next(iter(self._sizes)))
        return value

    def snapshot(self, store, session_id, summary):
        key = (session_id, summary["run_id"])
        revision = (summary["event_seq"], summary["updated_at"])
        cached = self._cached("snapshots", key)
        if cached is None or cached[0] != revision:
            value = store.get(summary["run_id"])
            if value["session_id"] != session_id:
                raise ValueError("Run does not belong to the selected conversation")
            cached = self._save("snapshots", key, (revision, value))
        return cached[1]

    def artifact(self, store, session_id, run_id, artifact_id):
        key = (session_id, run_id, artifact_id)
        cached = self._cached("artifacts", key)
        if cached is None:
            return self._save("artifacts", key, store.artifact(run_id, artifact_id))
        return cached

    def read_events(self, store, session_id, run_id):
        key = (session_id, run_id)
        cached = self._cached("events", key)
        events = cached if cached is not None else []
        changed = False
        cursor = events[-1]["seq"] if events else 0
        while True:
            page = store.events(run_id, after=cursor)
            if page:
                if any(event["seq"] != cursor + offset + 1 for offset, event in enumerate(page)):
                    raise RuntimeError("Run event sequence has a gap; reload this run explicitly")
                if not changed:
                    events = list(events)
                    changed = True
                events.extend(page)
                cursor = events[-1]["seq"]
            if len(page) < 500:
                break
        return self._save("events", key, events) if changed or cached is None else cached
