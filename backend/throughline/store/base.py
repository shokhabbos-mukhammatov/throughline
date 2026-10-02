"""Storage interface. Documents are plain dicts grouped per partition and per kind.

A partition is either the shared course catalog or one course (its map, question bank and
responses). Two implementations share the interface: an in-memory store with a JSON snapshot for
local development and tests, and Firestore (spaces/{partition}/{kind}/{id}) in production.
"""

from __future__ import annotations

from typing import Any, Protocol


class Store(Protocol):
    def get(self, part: str, kind: str, id: str) -> dict | None: ...

    def put(self, part: str, kind: str, id: str, data: dict) -> None: ...

    def put_many(self, part: str, kind: str, items: list[tuple[str, dict]]) -> None: ...

    def list(self, part: str, kind: str, where: dict[str, Any] | None = None) -> list[dict]: ...

    def delete_many(self, part: str, kind: str, ids: list[str]) -> None: ...

    def delete_partition(self, part: str) -> None: ...


def matches(doc: dict, where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    for key, expected in where.items():
        value = doc.get(key)
        if isinstance(expected, (list, tuple, set)):
            if value not in expected:
                return False
        elif value != expected:
            return False
    return True
