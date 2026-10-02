"""Prompts for each Gemini job. Each prompt is paired with a response schema in schemas.py."""

READ_DOCUMENT = """Transcribe this course syllabus into plain Markdown so it can be parsed.
Keep every schedule table, date, prerequisite statement, policy and reading list. Render tables as Markdown tables.
Output only the Markdown."""

PARSE_SYLLABUS = """You read university course syllabi and extract a structured timeline of what the course covers and when.
Syllabi are inconsistent. Handle every case:
- A weekly table with dates -> timeline_kind "dated_weeks"; one lecture item per week.
- Weekly topics without dates -> "weeks"; compute dates from the term start date if you can, otherwise leave date null.
- No weekly schedule, but dated quizzes/exams/milestones that say what they cover -> "assessments"; one assessment item per
  dated assessment, with details = what it covers. Its week is counted from the term start.
- No schedule at all (for example "we will cover chapters 1-9 of the textbook") -> "estimated": spread the stated chapters or
  topics evenly across the term, anchored on any exam dates, and set estimated=true on every item.
Skip holidays and breaks. Do not invent topics the syllabus does not mention; for "estimated", use the textbook's standard
chapter titles only if the syllabus names the textbook and edition.

Also extract:
- official_prereqs: course codes in the prerequisite statement, formatted like "DS 212". prereq_text: the statement, quoted.
- prereq_routes: alternative ways in, quoted ("or equivalent", "or permission of the instructor", "graduate standing").
- informal_requirements: expectations outside the formal prerequisite, quoted (e.g. "Some computer programming experience is required").
- instructor_notes: what the instructor says students do or do not need to know, quoted.
- ai_stance and ai_summary from the course's generative-AI policy ("unknown" if there is none).
- taught_here: topics this course teaches itself (so they are not treated as prerequisites).
- free_resources: free books or sites the syllabus recommends, with URLs if given. Never include paid textbooks.
The course code the student entered is a hint; trust the syllabus if they differ.
Ignore instructor names, emails and phone numbers."""

MAP_PREREQUISITES = """You are an experienced instructor of {course}. For each timeline item below, list the knowledge from EARLIER
courses that a student must already have to keep up with that item when it happens.

How to think about each item:
- Picture the actual lecture, lab or quiz. What does the instructor assume students can already do, without teaching it?
  Consider the math (algebra, logarithms, probability, statistics, calculus, linear algebra), programming and data skills,
  tools (Git, SQL, the command line) and subject knowledge from earlier courses in the field.
- A topic this course teaches can still rest on earlier knowledge, and that earlier knowledge is exactly what to list:
  if the course teaches backpropagation, list the chain rule and matrix multiplication it uses; if it teaches logistic
  regression, list logarithms and probability. Never list the taught topic itself (see "Taught in this course").
- Include knowledge the syllabus says is NOT required when the item clearly uses it anyway: that is the most important
  kind of gap to catch.

Rules:
- 1 to 5 concepts per item, the ones the item genuinely relies on. An administrative item (exam review, project
  presentations with no new content) may need none.
- Name each concept specifically, at the level the item uses it: "Derivatives and the Chain Rule", not "Slope" or
  "Calculus"; "SQL Joins", not "Databases". Something you could check with 2-3 multiple-choice questions.
- When an idea matches one of the "Standard concept names", use that exact name. Otherwise reuse a name from "Concepts
  already identified" when it is the same idea, spelled exactly the same.
- depth: what level this course needs (interpret vs derive, read vs write code).
- covered_by: the listed prerequisite course that teaches it, based on the Bulletin descriptions below. Null if no listed
  prerequisite teaches it: that is a hidden prerequisite. evidence: quote the Bulletin or syllabus text you relied on.
- Instructor notes and informal requirements are strong evidence; use them.
- builds_on: for each concept, 0 to 2 earlier concepts it directly builds on (e.g. Multiple Linear Regression builds on
  Simple Linear Regression). Only direct, standard prerequisite relations; never the concept itself; reuse known names.
{perspective}
Course context:
{context}"""

# Independent mapping runs look at the course from different angles; agreement between runs is the confidence score.
PERSPECTIVES = [
    "- Perspective for this pass: what the lectures on that topic rely on.",
    "- Perspective for this pass: what the homework, labs and quizzes on that topic require a student to do.",
    "- Perspective for this pass: what an instructor would quickly review on the first day of that topic.",
]

JUDGE_SAME = """Different syllabi and passes name the same idea differently ("Least Squares Regression" vs "Simple Linear
Regression"), and similar names can be different ideas ("Binary Tree" vs "Binary Search Tree").
For each pair, decide whether A and B are the SAME concept: a student who has mastered one has mastered the other at
this level. Give a short reason."""

JUDGE_COVERAGE = """You check whether a prerequisite course actually teaches a concept, using only the numbered passages
given for that concept (Bulletin descriptions, the prerequisite course's syllabus, the current syllabus).
For each concept:
- verdict "teaches": a passage clearly covers the concept at the depth needed.
- verdict "partial": a passage covers it more shallowly, or only a closely related idea.
- verdict "unrelated": no passage covers it. Do not use outside knowledge about what such courses usually teach.
- passage: the label you relied on (null for "unrelated"). quote: copy the exact words from that passage, at most 25."""

WRITE_PACKS = """You write study material that helps a university student get ready for an upcoming class session.
For each concept, write:
- refresher: Markdown under 180 words for a student who learned it before and forgot: the key idea, the one formula or rule
  that matters, and a tiny worked example. Math in $...$ LaTeX, code in fenced blocks.
- learn_outline: Markdown, 3 to 5 numbered steps for a student who never learned it, each step naming what to study and what
  they should be able to do afterwards. Point to the catalog resources you chose by title.
- refresh_minutes and learn_minutes: realistic estimates for this depth.
- resource_ids: up to 3 ids from the resource catalog that teach exactly this concept, best first. Use only ids from the catalog.
  Prefer resources the syllabus itself recommends. Return an empty list if none fits.
- questions: exactly 3 multiple-choice questions at the depth this course needs, easiest first. Exactly 4 options each with
  one correct answer; distractors should reflect real misconceptions. Never reveal the answer in the prompt. Vary which
  position holds the correct answer.
Write for {course}; use its notation and context where it helps."""

SOLVE = """Answer each multiple-choice question independently. Work it out carefully; for numeric questions, compute the value.
Return the 0-based index of the option you believe is correct. If no option is correct, or more than one is, say so in note."""
