"""Firestore implementation: spaces/{partition}/{kind}/{id}.

Each course is its own partition, so one course's map and responses are physically separate from
every other course's.
"""

from __future__ import annotations

from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .base import matches

_BATCH = 400


class FirestoreStore:
    def __init__(self, project: str | None = None):
        self._db = firestore.Client(project=project)

    def _col(self, part: str, kind: str):
        return self._db.collection("spaces").document(part).collection(kind)

    def get(self, part: str, kind: str, id: str) -> dict | None:
        snap = self._col(part, kind).document(id).get()
        return snap.to_dict() if snap.exists else None

    def put(self, part: str, kind: str, id: str, data: dict) -> None:
        self._col(part, kind).document(id).set(data)

    def put_many(self, part: str, kind: str, items: list[tuple[str, dict]]) -> None:
        col = self._col(part, kind)
        for start in range(0, len(items), _BATCH):
            batch = self._db.batch()
            for id, data in items[start : start + _BATCH]:
                batch.set(col.document(id), data)
            batch.commit()

    def list(self, part: str, kind: str, where: dict[str, Any] | None = None) -> list[dict]:
        query = self._col(part, kind)
        post_filter: dict[str, Any] = {}
        for key, value in (where or {}).items():
            if isinstance(value, (list, tuple, set)):
                post_filter[key] = value  # small sets; filter in process
            else:
                query = query.where(filter=FieldFilter(key, "==", value))
        docs = [s.to_dict() for s in query.stream()]
        return [d for d in docs if matches(d, post_filter)]

    def delete_many(self, part: str, kind: str, ids: list[str]) -> None:
        col = self._col(part, kind)
        for start in range(0, len(ids), _BATCH):
            batch = self._db.batch()
            for id in ids[start : start + _BATCH]:
                batch.delete(col.document(id))
            batch.commit()

    def delete_partition(self, part: str) -> None:
        self._db.recursive_delete(self._db.collection("spaces").document(part))
