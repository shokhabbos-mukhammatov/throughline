"""Typed views over the dict store.

Partitions: one shared catalog of courses, and one partition per course holding its map,
question bank and responses.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from .models import BankQuestion, Concept, Course, Edge, Enrollment, Material, Requirement, Response, Topic
from .store import Store

T = TypeVar("T", bound=BaseModel)

CATALOG = "_catalog"


class Collection(Generic[T]):
    def __init__(self, store: Store, partition: str, kind: str, model: type[T]):
        self._store, self._part, self._kind, self._model = store, partition, kind, model

    def get(self, id: str) -> T | None:
        raw = self._store.get(self._part, self._kind, id)
        return self._model.model_validate(raw) if raw else None

    def put(self, item: T) -> T:
        self._store.put(self._part, self._kind, item.id, item.model_dump(mode="json"))  # type: ignore[attr-defined]
        return item

    def put_many(self, items: list[T]) -> None:
        if items:
            self._store.put_many(self._part, self._kind, [(i.id, i.model_dump(mode="json")) for i in items])  # type: ignore[attr-defined]

    def list(self, **where: Any) -> list[T]:
        return [self._model.model_validate(d) for d in self._store.list(self._part, self._kind, where or None)]

    def delete_many(self, ids: list[str]) -> None:
        if ids:
            self._store.delete_many(self._part, self._kind, ids)


class Catalog:
    """Every course, findable by id, owner or join code."""

    def __init__(self, store: Store):
        self.courses = Collection(store, CATALOG, "courses", Course)

    def get(self, course_id: str) -> Course | None:
        return self.courses.get(course_id)

    def put(self, course: Course) -> Course:
        return self.courses.put(course)

    def by_join_code(self, code: str) -> Course | None:
        found = self.courses.list(join_code=code.strip().upper())
        return found[0] if found else None

    def all(self) -> list[Course]:
        return self.courses.list()

    def owned_by(self, uid: str) -> list[Course]:
        return sorted(self.courses.list(owner=uid), key=lambda c: c.created_at, reverse=True)


class CourseRepo:
    """One course's shared map plus its students' responses."""

    def __init__(self, store: Store, course_id: str):
        self.store = store
        self.course_id = course_id
        self.topics = Collection(store, course_id, "topics", Topic)
        self.concepts = Collection(store, course_id, "concepts", Concept)
        self.edges = Collection(store, course_id, "edges", Edge)
        self.requirements = Collection(store, course_id, "requirements", Requirement)
        self.questions = Collection(store, course_id, "questions", BankQuestion)
        self.responses = Collection(store, course_id, "responses", Response)
        self.enrollments = Collection(store, course_id, "enrollments", Enrollment)
        self.materials = Collection(store, course_id, "materials", Material)

    def clear_map(self) -> None:
        for col in (self.topics, self.concepts, self.edges, self.requirements, self.questions):
            col.delete_many([x.id for x in col.list()])  # type: ignore[attr-defined]

    def wipe(self) -> None:
        self.store.delete_partition(self.course_id)
