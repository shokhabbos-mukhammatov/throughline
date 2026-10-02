import { identityHeaders } from "./session";

export type Status = "ready" | "likely" | "refresh" | "learn" | "unchecked";
export type Coverage = "listed" | "likely" | "missing" | "unknown";
export type Route = "took_here" | "equivalent" | "permission" | "unsure";
export type SelfReport = "yes" | "never" | "unsure";
export type TimelineKind = "dated_weeks" | "weeks" | "assessments" | "estimated";

export interface Resource {
  title: string;
  url: string | null;
  detail: string;
  kind: "syllabus" | "open_textbook" | "web";
}

export interface BulletinEntry {
  code: string;
  title: string;
  description: string;
  prerequisites: string;
  prereq_codes: string[];
  source: string;
}

export interface StageTrace {
  stage: string;
  ms: number;
  calls: Record<string, number>;
  notes: string[];
}

export interface Build {
  status: "queued" | "running" | "ready" | "error";
  stage: string;
  done: number;
  total: number;
  error: string | null;
  error_kind?: "syllabus" | "service" | "internal" | "";
  trace: StageTrace[];
}

export interface CoursePublic {
  id: string;
  code: string;
  title: string;
  term: string;
  term_start: string | null;
  term_end: string | null;
  official_prereqs: string[];
  prereq_text: string;
  prereq_routes: string[];
  informal_requirements: string[];
  instructor_notes: string[];
  ai_policy: { stance: "encouraged" | "limited" | "prohibited" | "unknown"; summary: string };
  timeline_kind: TimelineKind;
  resources: Resource[];
  bulletin: BulletinEntry[];
  prereq_docs: string[];
  join_code: string;
  demo: boolean;
  build: Build;
}

export interface NextNeed {
  week: number;
  date: string;
  title: string;
  how_used: string;
  importance: "essential" | "helpful";
  overdue: boolean;
  via: string | null;
}

export interface NoteHit {
  material_id: string;
  file: string;
  label: string;
  loc: string;
  quote: string;
  verdict: "teaches" | "partial";
}

/** One concrete place to study a concept: the student's own notes first, then free resources. */
export interface StudySource {
  kind: "notes" | "syllabus" | "open_textbook" | "web";
  title: string;
  detail: string;
  url: string | null;
  quote: string;
}

export interface Material {
  id: string;
  filename: string;
  prereq_code: string;
  kind: string;
  parts: number;
  created_at: string;
  covers: { concept_id: string; name: string; locs: string[] }[];
}

export interface ConceptView {
  id: string;
  name: string;
  summary: string;
  depth: string;
  foundation: boolean;
  confidence: number;
  covered_by: string | null;
  coverage: Coverage;
  hidden: boolean;
  in_your_notes: NoteHit[];
  status: Status;
  status_label: string;
  p: number;
  basis: string;
  self_report: SelfReport | null;
  correct: number;
  attempts: number;
  builds_on: string[];
  next_need: NextNeed | null;
  minutes: number;
}

export interface TimelineItem {
  id: string;
  week: number;
  date: string;
  date_stated: boolean;
  title: string;
  details: string;
  kind: "lecture" | "assessment";
  estimated: boolean;
  past: boolean;
  requires: { concept_id: string; name: string; importance: string; how_used: string; status: Status }[];
}

export interface Enrollment {
  id: string;
  route: Route;
  prereq_taken: string | null;
  weekly_minutes: number;
  self_report: Record<string, SelfReport>;
}

export interface CourseDetail extends CoursePublic {
  is_owner: boolean;
  engine: { label: string; online: boolean };
  week_now?: number;
  enrolled?: boolean;
  enrollment?: Enrollment;
  timeline?: TimelineItem[];
  concepts?: ConceptView[];
}

export interface PlanItem {
  concept_id: string;
  name: string;
  status: Status;
  status_label: string;
  minutes: number;
  total_minutes: number;
  partial: boolean;
  due: string;
  do_by: string;
  overdue: boolean;
  for_week: number;
  for_title: string;
  for_kind: string;
  foundation_for: string | null;
  before: string | null;
  importance: string;
  coverage: Coverage;
  hidden: boolean;
  study: StudySource[];
  short_by?: number;
}

export interface Plan {
  today: string;
  week_now: number;
  weekly_minutes: number;
  total_minutes: number;
  counts: { ready: number; to_do: number; learn: number; refresh: number; unchecked: number; likely: number; foundations: number; overdue: number };
  weeks: { start: string; end: string; capacity: number; minutes: number; items: PlanItem[] }[];
  at_risk: PlanItem[];
}

export interface Question {
  id: string;
  concept_id: string;
  prompt: string;
  choices: string[];
  concept_name?: string;
  next_need?: NextNeed | null;
}

export interface AnswerResult {
  response_id: string;
  question_id: string;
  concept_id: string;
  correct: boolean;
  correct_index: number;
  explanation: string;
  status_before: Status;
  status_after: Status;
  status_label: string;
  p_before: number;
  p_after: number;
  basis: string;
  correct_count: number;
  attempts: number;
  also_changed: { concept_id: string; name: string; p_before: number; p_after: number; status_before: Status; status_after: Status }[];
}

export interface CheckStep {
  done: boolean;
  asked: number;
  max_questions?: number;
  question?: Question;
  reason?: string;
  gain_bits?: number;
  focus: ConceptView[];
}

export interface Evidence {
  source: string;
  quote: string;
  verdict: "teaches" | "partial" | "unrelated";
}

export interface GraphData {
  nodes: { id: string; name: string; status: Status; p: number; coverage: Coverage; covered_by: string | null; foundation: boolean; confidence: number; depth: number; next_need: NextNeed | null }[];
  edges: { src: string; dst: string; confidence: number }[];
  needs: { concept_id: string; week: number; importance: string }[];
  weeks: number[];
  week_now: number;
  prereqs: string[];
}

export interface Study extends ConceptView {
  evidence: string;
  evidence_items: Evidence[];
  aliases: string[];
  leads_to: string[];
  refresher: string;
  learn_outline: string;
  refresh_minutes: number;
  learn_minutes: number;
  resources: Resource[];
  where_to_learn: StudySource[];
  uses: { week: number; date: string; title: string; kind: string; how_used: string; importance: string; past: boolean }[];
  practice: Question | null;
}

export interface ReviewQuestion {
  id: string;
  concept_id: string;
  prompt: string;
  choices: string[];
  correct_index: number;
  explanation: string;
  status: "draft" | "approved" | "rejected";
  verification: "agreed" | "disagreed" | "unverified";
  verification_note: string;
  origin: string;
}

export interface ReviewConcept {
  id: string;
  name: string;
  aliases: string[];
  summary: string;
  depth: string;
  foundation: boolean;
  confidence: number;
  covered_by: string | null;
  coverage: Coverage;
  hidden: boolean;
  evidence: string;
  evidence_items: Evidence[];
  removed: boolean;
  resources: Resource[];
  questions: ReviewQuestion[];
}

export interface Review {
  concepts: ReviewConcept[];
  flagged: number;
  edges: { src: string; dst: string; confidence: number }[];
  trace: StageTrace[];
  prereq_docs: string[];
}

export interface ClassRow {
  concept_id: string;
  name: string;
  covered_by: string | null;
  coverage: Coverage;
  hidden: boolean;
  weeks: number[];
  first_week: number;
  first_date: string;
  first_title: string;
  upcoming: boolean;
  n: number;
  suppressed: boolean;
  first_try: number | null;
  never: number | null;
  ready: number | null;
}

export interface ClassView {
  week_now: number;
  weeks: number[];
  students: number;
  simulated: number;
  min_cell: number;
  rows: ClassRow[];
  concerns: ClassRow[];
}

/* ---------- identity: an anonymous id kept in this browser ---------- */

const UID_KEY = "throughline.uid";
const JOINED_KEY = "throughline.joined";

function randomId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return "u_" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

let memoryUid: string | null = null;
export function uid(): string {
  try {
    let v = localStorage.getItem(UID_KEY);
    if (!v) {
      v = randomId();
      localStorage.setItem(UID_KEY, v);
    }
    return v;
  } catch {
    memoryUid ??= randomId();
    return memoryUid;
  }
}

export function joinedCourses(): string[] {
  try {
    return JSON.parse(localStorage.getItem(JOINED_KEY) || "[]");
  } catch {
    return [];
  }
}

export function rememberCourse(id: string) {
  try {
    const list = joinedCourses().filter((x) => x !== id);
    localStorage.setItem(JOINED_KEY, JSON.stringify([id, ...list].slice(0, 20)));
  } catch {
    /* storage may be unavailable */
  }
}

/* ---------- fetch ---------- */

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  for (const [k, v] of Object.entries(await identityHeaders(uid))) headers.set(k, v);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  health: () => req<{ ok: boolean; engine: string; online: boolean }>("/api/health"),
  bulletin: (code: string) => req<BulletinEntry>(`/api/bulletin/${encodeURIComponent(code)}`),
  addCourse: (code: string, file: File | null, text: string, prereq?: { code: string; file: File } | null) => {
    const form = new FormData();
    form.set("code", code);
    if (file) form.set("file", file);
    if (text.trim()) form.set("text", text);
    if (prereq) {
      form.set("prereq_code", prereq.code);
      form.set("prereq_file", prereq.file);
    }
    return req<CoursePublic>("/api/courses", { method: "POST", body: form });
  },
  addPrereqSyllabus: (id: string, code: string, file: File) => {
    const form = new FormData();
    form.set("prereq_code", code);
    form.set("file", file);
    return req<CoursePublic>(`/api/courses/${id}/prereq-syllabus`, { method: "POST", body: form });
  },
  sample: () => req<CoursePublic>("/api/demo/sample", { method: "POST" }),
  mine: () => req<CoursePublic[]>("/api/courses/mine"),
  join: (code: string) => req<CoursePublic>(`/api/join/${encodeURIComponent(code.trim().toUpperCase())}`),
  course: (id: string) => req<CourseDetail>(`/api/courses/${id}`),
  updateMe: (id: string, body: Partial<Pick<Enrollment, "route" | "weekly_minutes" | "self_report">> & { prereq_taken?: string }) =>
    req<Enrollment>(`/api/courses/${id}/me`, { method: "PUT", body: json(body) }),
  plan: (id: string) => req<Plan>(`/api/courses/${id}/plan`),
  checkNext: (id: string, session: string[]) => req<CheckStep>(`/api/courses/${id}/check/next`, { method: "POST", body: json({ session }) }),
  deleteMe: (id: string) => req<{ deleted_responses: number; deleted_materials: number }>(`/api/courses/${id}/me`, { method: "DELETE" }),
  materials: (id: string) => req<Material[]>(`/api/courses/${id}/materials`),
  addMaterial: (id: string, file: File, prereqCode: string) => {
    const form = new FormData();
    form.set("file", file);
    form.set("prereq_code", prereqCode);
    return req<Material>(`/api/courses/${id}/materials`, { method: "POST", body: form });
  },
  deleteMaterial: (id: string, materialId: string) => req<{ deleted: string }>(`/api/courses/${id}/materials/${materialId}`, { method: "DELETE" }),
  graph: (id: string) => req<GraphData>(`/api/courses/${id}/graph`),
  answer: (id: string, question_id: string, choice: number, phase: "check" | "practice") =>
    req<AnswerResult>(`/api/courses/${id}/answer`, { method: "POST", body: json({ question_id, choice, phase }) }),
  study: (id: string, conceptId: string) => req<Study>(`/api/courses/${id}/concepts/${conceptId}`),
  review: (id: string) => req<Review>(`/api/courses/${id}/review`),
  patchQuestion: (id: string, qid: string, body: Partial<ReviewQuestion>) =>
    req<ReviewQuestion>(`/api/courses/${id}/questions/${qid}`, { method: "PATCH", body: json(body) }),
  patchConcept: (id: string, cid: string, body: { removed: boolean }) =>
    req<ReviewConcept>(`/api/courses/${id}/concepts/${cid}`, { method: "PATCH", body: json(body) }),
  rebuild: (id: string) => req<CoursePublic>(`/api/courses/${id}/rebuild`, { method: "POST" }),
  classView: (id: string, includeSimulated: boolean) => req<ClassView>(`/api/courses/${id}/class?include_simulated=${includeSimulated}`),
};
