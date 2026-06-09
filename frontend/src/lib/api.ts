/**
 * Minimal API client for the TCF AI Tutor backend.
 *
 * Base URL comes from NEXT_PUBLIC_API_URL (inlined at build time, so it must
 * be prefixed NEXT_PUBLIC_ to reach the browser); falls back to the local
 * backend default.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Exam section a question belongs to (matches backend ExamSection enum). */
export type ExamSection = "writing" | "speaking" | "listening" | "reading";

/** CEFR level (matches backend DifficultyLevel enum). */
export type DifficultyLevel = "A1" | "A2" | "B1" | "B2" | "C1" | "C2";

/** Shape of one row from `GET /questions` (matches backend QuestionOut). */
export type Question = {
  id: string;
  exam_section: ExamSection;
  task_number: number;
  prompt: string;
  instructions: string;
  time_limit_seconds: number;
  word_count_min: number;
  word_count_max: number;
  difficulty_level: DifficultyLevel;
  source: string | null;
};

/** Fetch the full question list from the backend. */
export async function getQuestions(): Promise<Question[]> {
  const res = await fetch(`${API_BASE_URL}/questions`);
  if (!res.ok) {
    throw new Error(`GET /questions failed: HTTP ${res.status}`);
  }
  return res.json();
}
