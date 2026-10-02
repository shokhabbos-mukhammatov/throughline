"""In-memory store with an optional JSON snapshot so local data survives restarts."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from typing import Any

from .base import matches


class MemoryStore:
    def __init__(self, path: str | None = None, flush_interval: float = 1.5):
        self._data: dict[str, dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
        self._lock = threading.RLock()
        self._path = path
        self._dirty = False
        if path and os.path.exists(path):
            self._load()
        if path:
            thread = threading.Thread(target=self._flusher, args=(flush_interval,), daemon=True)
            thread.start()
    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        for part, kinds in raw.items():
            for kind, docs in kinds.items():
                self._data[part][kind] = docs

    def _flusher(self, interval: float) -> None:
        while True:
            time.sleep(interval)
            self.flush()

    def flush(self) -> None:
        if not self._path or not self._dirty:
            return
        with self._lock:
            snapshot = json.dumps(self._data, default=str)
            self._dirty = False
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(snapshot)
        os.replace(tmp, self._path)
    def get(self, part: str, kind: str, id: str) -> dict | None:
        with self._lock:
            doc = self._data[part][kind].get(id)
            return dict(doc) if doc is not None else None

    def put(self, part: str, kind: str, id: str, data: dict) -> None:
        with self._lock:
            self._data[part][kind][id] = dict(data)
            self._dirty = True

    def put_many(self, part: str, kind: str, items: list[tuple[str, dict]]) -> None:
        with self._lock:
            for id, data in items:
                self._data[part][kind][id] = dict(data)
            self._dirty = True

    def list(self, part: str, kind: str, where: dict[str, Any] | None = None) -> list[dict]:
        with self._lock:
            return [dict(d) for d in self._data[part][kind].values() if matches(d, where)]

    def delete_many(self, part: str, kind: str, ids: list[str]) -> None:
        with self._lock:
            for id in ids:
                self._data[part][kind].pop(id, None)
            self._dirty = True

    def delete_partition(self, part: str) -> None:
        with self._lock:
            self._data.pop(part, None)
            self._dirty = True
