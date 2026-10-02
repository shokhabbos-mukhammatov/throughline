from __future__ import annotations

import logging

from ..config import Settings
from .base import (
    ConceptCard,
    CourseContext,
    CoverageRequest,
    Engine,
    EngineUnavailable,
    EvidencePassage,
    ItemCard,
    PairCard,
    QuestionCard,
    ResourceCard,
)

log = logging.getLogger(__name__)


def make_engine(settings: Settings) -> Engine:
    if settings.gemini_configured:
        from .gemini import GeminiEngine

        return GeminiEngine(settings)
    from .offline import OfflineEngine

    log.warning("Gemini is not configured; using the offline heuristic engine.")
    return OfflineEngine()


__all__ = [
    "ConceptCard",
    "CourseContext",
    "CoverageRequest",
    "Engine",
    "EngineUnavailable",
    "EvidencePassage",
    "ItemCard",
    "PairCard",
    "QuestionCard",
    "ResourceCard",
    "make_engine",
]
