from __future__ import annotations

import os

from ..config import Settings
from .base import Store


def make_store(settings: Settings) -> Store:
    if settings.store == "firestore":
        from .firestore_store import FirestoreStore

        return FirestoreStore(project=settings.gcp_project)
    from .memory import MemoryStore

    path = os.path.join(settings.data_dir, "store.json") if settings.persist else None
    return MemoryStore(path=path)


__all__ = ["Store", "make_store"]
