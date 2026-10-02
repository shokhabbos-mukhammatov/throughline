import type { Coverage, Route, Status, TimelineKind } from "./api";

export const pct = (p: number | null | undefined) => (p == null ? "–" : `${Math.round(p * 100)}%`);

export const STATUS_LABEL: Record<Status, string> = {
  ready: "Ready",
  likely: "Probably known",
  refresh: "Refresh",
  learn: "Learn",
  unchecked: "Not checked yet",
};

export const STATUS_HINT: Record<Status, string> = {
  ready: "85% or more likely you know it, based on your answers.",
  likely: "Probably known (60 to 85%). One more right answer would confirm it.",
  refresh: "You've studied this before but missed the last question. A short refresher should do it.",
  learn: "You haven't studied this yet. Plan for real study time, not a quick review.",
  unchecked: "Take a quick check to find out where you stand.",
};

export const COVERAGE_LABEL: Record<Coverage, { label: string; hint: string }> = {
  listed: { label: "Taught in", hint: "A listed prerequisite teaches it, and we found the passage that says so." },
  likely: { label: "Probably from", hint: "Usually part of the listed prerequisite, but the record doesn't confirm it." },
  missing: { label: "Not in listed prerequisites", hint: "The course needs it, and the evidence says no listed prerequisite teaches it." },
  unknown: { label: "Not confirmed", hint: "The Bulletin descriptions are too short to tell. Adding the prerequisite's syllabus settles it." },
};

export const ROUTE_LABEL: Record<Route, string> = {
  took_here: "I took the listed prerequisite at SF State",
  equivalent: "I took an equivalent course somewhere else",
  permission: "I got in with instructor permission or a waiver",
  unsure: "I'm not sure",
};

export const TIMELINE_LABEL: Record<TimelineKind, { label: string; hint: string }> = {
  dated_weeks: { label: "Dates from the syllabus", hint: "The syllabus gives a dated weekly schedule." },
  weeks: { label: "Weekly schedule", hint: "The syllabus lists topics by week; dates are counted from the term start." },
  assessments: { label: "From quiz and exam dates", hint: "The syllabus has no weekly schedule, so timing comes from what each dated assessment covers." },
  estimated: { label: "Estimated timing", hint: "The syllabus has no schedule; topics were spread across the term. Treat dates as rough." },
};

export const AI_LABEL = {
  encouraged: "AI encouraged as a tutor",
  limited: "AI allowed with limits",
  prohibited: "AI prohibited for coursework",
  unknown: "No AI policy found",
} as const;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  return `${MONTHS[m - 1]} ${d}`;
}

export function minutes(total: number): string {
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function daysUntil(iso: string | null, today = new Date()): number | null {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const target = Date.UTC(y, m - 1, d);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - now) / 86400000);
}

export function dueLabel(iso: string, overdue = false): string {
  if (overdue) return "Already in use";
  const d = daysUntil(iso);
  if (d == null) return "";
  if (d <= 0) return "Needed now";
  if (d === 1) return "Needed tomorrow";
  if (d < 7) return `Needed in ${d} days`;
  return `Needed by ${shortDate(iso)}`;
}
