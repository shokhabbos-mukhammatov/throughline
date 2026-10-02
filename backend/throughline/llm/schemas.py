"""Structured-output schemas. Every Gemini call returns JSON validated against one of these."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TimelineItem(BaseModel):
    week: int = Field(description="Week of the term, starting at 1. Estimate it when the syllabus only gives a date.")
    date: str | None = Field(default=None, description="ISO date (YYYY-MM-DD) if the syllabus states or clearly implies it.")
    title: str
    details: str = Field(default="", description="Topics covered, or what an assessment covers.")
    kind: Literal["lecture", "assessment"] = "lecture"
    estimated: bool = Field(default=False, description="True when the timing is inferred rather than stated.")


class FreeResource(BaseModel):
    title: str
    url: str | None = None
    detail: str = ""


class SyllabusParse(BaseModel):
    code: str = Field(description="Course code like 'DS 612'. If cross-listed, the undergraduate code.")
    title: str = ""
    term: str = Field(default="", description="Like 'Fall 2026'.")
    term_start: str | None = Field(default=None, description="ISO date of the first class, if determinable.")
    term_end: str | None = Field(default=None, description="ISO date of the last class or final exam, if determinable.")
    official_prereqs: list[str] = Field(default_factory=list, description="Course codes listed as prerequisites.")
    prereq_text: str = Field(default="", description="The prerequisite sentence, quoted.")
    prereq_routes: list[str] = Field(
        default_factory=list, description="Alternative ways in, quoted: 'or equivalent', 'or permission of the instructor', ..."
    )
    informal_requirements: list[str] = Field(
        default_factory=list, description="Expectations stated outside the formal prerequisite, quoted."
    )
    instructor_notes: list[str] = Field(
        default_factory=list, description="Instructor statements about what students do or do not need to know, quoted."
    )
    ai_stance: Literal["encouraged", "limited", "prohibited", "unknown"] = "unknown"
    ai_summary: str = Field(default="", description="One or two sentences on what the course allows students to use AI for.")
    timeline_kind: Literal["dated_weeks", "weeks", "assessments", "estimated"]
    timeline: list[TimelineItem]
    taught_here: list[str] = Field(default_factory=list, description="Topics this course itself teaches, in its own words.")
    free_resources: list[FreeResource] = Field(
        default_factory=list, description="Free materials the syllabus recommends (free books, sites). Not paid textbooks."
    )


class Foundation(BaseModel):
    name: str = Field(description="Canonical name of an earlier concept this one builds on.")
    summary: str = Field(default="", description="One-sentence definition.")


class RequiredConcept(BaseModel):
    name: str = Field(description="Canonical textbook name in Title Case. Reuse an existing name when it is the same idea.")
    summary: str = Field(description="One sentence a student could use as a definition.")
    importance: Literal["essential", "helpful"]
    how_used: str = Field(description="One concrete sentence on how this timeline item uses it.")
    depth: str = Field(description="How deep this course needs it, e.g. 'interpret slope and R-squared; no derivations'.")
    covered_by: str | None = Field(default=None, description="Listed prerequisite course code that teaches it, or null.")
    evidence: str = Field(default="", description="The syllabus line or Bulletin description that supports covered_by or hidden.")
    builds_on: list[Foundation] = Field(
        default_factory=list, description="0-2 earlier concepts this one directly builds on (its own prerequisites)."
    )


class ItemRequirements(BaseModel):
    item_id: str
    requires: list[RequiredConcept] = Field(default_factory=list)


class MappingResult(BaseModel):
    items: list[ItemRequirements]


class GeneratedQuestion(BaseModel):
    prompt: str
    choices: list[str] = Field(description="Exactly 4 options.")
    correct_index: int = Field(description="0-based index of the single correct option.")
    explanation: str = Field(description="2-3 sentences on why the correct option is right.")


class ConceptPack(BaseModel):
    concept_id: str
    refresher: str = Field(description="Markdown, under 180 words, for a student who learned this before.")
    learn_outline: str = Field(description="Markdown study path for a student who never learned it: 3-5 steps.")
    refresh_minutes: int = Field(ge=5, le=60)
    learn_minutes: int = Field(ge=30, le=600)
    resource_ids: list[str] = Field(default_factory=list, description="Ids from the resource catalog, best first, at most 3.")
    questions: list[GeneratedQuestion] = Field(description="Exactly 3 multiple-choice questions, easiest first.")


class ConceptPacks(BaseModel):
    packs: list[ConceptPack]


class Solution(BaseModel):
    question_id: str
    choice: int = Field(description="0-based index of the option you believe is correct.")
    note: str = Field(default="", description="If no option is correct or several are, say so.")


class Solutions(BaseModel):
    solutions: list[Solution]


class PairJudgment(BaseModel):
    pair_id: str
    same: bool = Field(description="True if mastering one means mastering the other.")
    reason: str = ""


class SameConceptJudgments(BaseModel):
    judgments: list[PairJudgment]


class CoverageJudgment(BaseModel):
    concept_id: str
    verdict: Literal["teaches", "partial", "unrelated"] = Field(
        description="Does the best passage teach this concept at the depth needed? 'unrelated' if no passage does."
    )
    passage: str | None = Field(default=None, description="Label of the passage you relied on, like p3, or null.")
    quote: str = Field(default="", description="The exact words from that passage (at most 25 words) that show it.")


class CoverageJudgments(BaseModel):
    judgments: list[CoverageJudgment]
