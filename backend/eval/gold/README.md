# Gold labels for the evaluation harness

Each file says what a good course map for one syllabus must contain. **These are drafts written by the team
from reading each syllabus and the SF State Bulletin. Correct them before trusting the numbers.**

- `required`: prior knowledge the course clearly relies on. Missing one lowers recall.
  `week` is the first week (counted from the term start) that needs it; `coverage` is what the record should say.
- `acceptable`: reasonable to list, never counted as an error.
- `taught_here`: topics the course itself teaches; listing one as a prerequisite counts as an error.
- `file`: the syllabus file name to look for in the files folder (real syllabi stay in `private/`, never in git).
  `@sample` uses the built-in fictional sample syllabus.

Run: `python scripts/evaluate.py --files ../private` (from `backend/`, with `GEMINI_API_KEY` set for real results).

Scoring notes:

- A required concept that the pipeline found only as a foundation (added because something it found builds on it)
  counts toward recall, not toward week accuracy, and is listed separately in the output.
- `sample_demo410.json` labels our own fictional course, so its score only shows that the harness runs.
  Report the mean over real syllabi.
