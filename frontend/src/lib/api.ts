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

/** Status of a submitted answer (matches backend AnswerStatus enum). */
export type AnswerStatus = "draft" | "submitted";

/** Shape returned by `POST /answers` (matches backend AnswerOut). */
export type AnswerOut = {
  id: string;
  user_id: string;
  question_id: string;
  content: string;
  status: AnswerStatus;
};

/** One concrete fix tied to an excerpt of the essay. */
export type Correction = {
  original: string;
  correction: string;
  explanation: string;
};

/** The four rubric dimensions, each scored 0–6. */
export type DimensionScores = {
  task_fulfillment: number;
  coherence: number;
  vocabulary: number;
  grammar: number;
};

/**
 * Grade returned by `POST /answers/{id}/grade` (matches backend FeedbackOut).
 * `estimated_level` is lifted out of dimension_scores server-side.
 */
export type EssayGrade = {
  id: string;
  answer_id: string;
  total_score: number;
  estimated_level: DifficultyLevel;
  dimension_scores: DimensionScores;
  corrections: Correction[];
  overall_comment: string;
  created_at: string;
};

/**
 * Throw an Error carrying the backend's `detail` message when present, so the
 * UI can show why a request failed (404 / 409 / 502 / 503) instead of a bare
 * status code.
 */
async function errorFrom(res: Response, label: string): Promise<Error> {
  let detail = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") {
      detail = body.detail;
    }
  } catch {
    // non-JSON body; keep the status-code message
  }
  return new Error(`${label}: ${detail}`);
}

/** Fetch the full question list from the backend. */
export async function getQuestions(): Promise<Question[]> {
  const res = await fetch(`${API_BASE_URL}/questions`);
  if (!res.ok) {
    throw await errorFrom(res, "GET /questions failed");
  }
  return res.json();
}

/** Submit an essay for a question; returns the stored answer (with its id). */
export async function submitAnswer(
  questionId: string,
  content: string,
): Promise<AnswerOut> {
  const res = await fetch(`${API_BASE_URL}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question_id: questionId, content }),
  });
  if (!res.ok) {
    throw await errorFrom(res, "POST /answers failed");
  }
  return res.json();
}

/**
 * Run the AI grader over a stored answer and return the grade.
 * Slow on purpose (three serial Claude calls, ~10–15s) — call this behind a
 * loading state.
 */
export async function gradeAnswer(answerId: string): Promise<EssayGrade> {
  const res = await fetch(`${API_BASE_URL}/answers/${answerId}/grade`, {
    method: "POST",
  });
  if (!res.ok) {
    throw await errorFrom(res, "Grading failed");
  }
  return res.json();
}
