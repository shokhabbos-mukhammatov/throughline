"""Shared services handed to every pipeline: the store, the AI engine and settings."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .config import Settings
from .llm import Engine
from .models import utcnow
from .repo import Catalog, CourseRepo
from .store import Store

_locks: dict[str, threading.RLock] = defaultdict(threading.RLock)
_locks_guard = threading.Lock()


def course_lock(course_id: str) -> threading.RLock:
    """Serializes writes to one course's map (builds and instructor edits)."""
    with _locks_guard:
        return _locks[course_id]


@dataclass
class Ctx:
    store: Store
    engine: Engine
    settings: Settings

    @property
    def catalog(self) -> Catalog:
        return Catalog(self.store)

    def course(self, course_id: str) -> CourseRepo:
        return CourseRepo(self.store, course_id)

    def now(self) -> datetime:
        return utcnow()

    def lock(self, course_id: str) -> threading.RLock:
        return course_lock(course_id)
