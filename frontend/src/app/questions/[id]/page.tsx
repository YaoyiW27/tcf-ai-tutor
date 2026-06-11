"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  getQuestions,
  gradeAnswer,
  submitAnswer,
  type EssayGrade,
  type Question,
} from "@/lib/api";

type QuestionState =
  | { kind: "loading" }
  | { kind: "ready"; question: Question }
  | { kind: "notfound" }
  | { kind: "error"; message: string };

type GradeState =
  | { kind: "idle" }
  | { kind: "grading" }
  | { kind: "done"; grade: EssayGrade }
  | { kind: "error"; message: string };

const DIMENSION_LABELS: Record<keyof EssayGrade["dimension_scores"], string> = {
  grammar: "Grammar",
  coherence: "Coherence",
  vocabulary: "Vocabulary",
  task_fulfillment: "Task fulfillment",
};

function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/).length;
}

export default function QuestionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const [state, setState] = useState<QuestionState>({ kind: "loading" });
  const [content, setContent] = useState("");
  const [grade, setGrade] = useState<GradeState>({ kind: "idle" });

  useEffect(() => {
    // Reuse the list endpoint and find by id — no per-question route yet.
    getQuestions()
      .then((questions) => {
        const question = questions.find((q) => q.id === id);
        setState(
          question ? { kind: "ready", question } : { kind: "notfound" },
        );
      })
      .catch((err) =>
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        }),
      );
  }, [id]);

  const wordCount = useMemo(() => countWords(content), [content]);

  if (state.kind === "loading") {
    return (
      <Centered>
        <p className="text-sm text-muted-foreground">Loading question…</p>
      </Centered>
    );
  }

  if (state.kind === "notfound") {
    return (
      <Centered>
        <p className="text-sm text-muted-foreground">Question not found.</p>
        <BackLink />
      </Centered>
    );
  }

  if (state.kind === "error") {
    return (
      <Centered>
        <p className="text-sm text-destructive">
          Failed to load question: {state.message}
        </p>
        <BackLink />
      </Centered>
    );
  }

  const { question } = state;
  const min = question.word_count_min;
  const max = question.word_count_max;
  const under = wordCount < min;
  const over = wordCount > max;
  const countColor = over
    ? "text-destructive"
    : under
      ? "text-amber-600"
      : "text-emerald-600";

  const grading = grade.kind === "grading";
  const canSubmit = !grading && content.trim() !== "";

  async function onSubmit() {
    setGrade({ kind: "grading" });
    try {
      const answer = await submitAnswer(question.id, content);
      const result = await gradeAnswer(answer.id);
      setGrade({ kind: "done", grade: result });
    } catch (err) {
      setGrade({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <BackLink />

      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">
            Task {question.task_number}
          </span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
            {question.difficulty_level}
          </span>
          <span className="ml-auto text-xs">
            {min}–{max} words
          </span>
        </div>
        <h1 className="text-xl font-semibold leading-relaxed">
          {question.prompt}
        </h1>
        <p className="whitespace-pre-line text-sm text-muted-foreground">
          {question.instructions}
        </p>
      </header>

      <section className="flex flex-col gap-2">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          disabled={grading}
          rows={12}
          placeholder="Écrivez votre réponse ici…"
          className="w-full resize-y rounded-lg border border-border bg-card p-4 text-sm leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        />
        <div className="flex items-center justify-between text-xs">
          <span className={countColor}>
            {wordCount} {wordCount === 1 ? "word" : "words"}
            {under && ` · ${min - wordCount} below minimum`}
            {over && ` · ${wordCount - max} over maximum`}
            {!under && !over && wordCount > 0 && " · within range"}
          </span>
          <span className="text-muted-foreground">
            target {min}–{max}
          </span>
        </div>
      </section>

      <Button onClick={onSubmit} disabled={!canSubmit} className="self-start">
        {grading ? "Grading…" : "Submit for grading"}
      </Button>

      {grading && (
        <p className="text-sm text-muted-foreground">
          Running the grader — three AI passes (score → find errors → verify).
          Please keep this tab open.
        </p>
      )}

      {grade.kind === "error" && (
        <p className="text-sm text-destructive">
          Something went wrong: {grade.message}
        </p>
      )}

      {grade.kind === "done" && <GradeReport grade={grade.grade} />}
    </main>
  );
}

function GradeReport({ grade }: { grade: EssayGrade }) {
  return (
    <section className="flex flex-col gap-5 rounded-lg border border-border bg-card p-5">
      {/* Headline: the official estimated level + NCLC + écrite band. */}
      <div className="flex flex-col gap-2 rounded-lg bg-primary/5 p-4">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Estimated TCF Canada level
        </span>
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="text-4xl font-bold tracking-tight">
            {grade.estimated_level}
          </span>
          {grade.nclc_level && (
            <span className="rounded-full bg-primary px-3 py-1 text-sm font-medium text-primary-foreground">
              {grade.nclc_level}
            </span>
          )}
          {grade.ecrit_band && (
            <span className="text-sm text-muted-foreground">
              Expression écrite{" "}
              <span className="font-semibold text-foreground">
                {grade.ecrit_band === "below 6" ? "non atteint" : grade.ecrit_band}
              </span>
              {grade.ecrit_band !== "below 6" && " / 20"}
            </span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
          <h3 className="text-sm font-medium">Dimension scores</h3>
          <span className="text-xs text-muted-foreground">
            Internal assessment — not official TCF points (avg{" "}
            {grade.total_score} / 6)
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            Object.keys(DIMENSION_LABELS) as (keyof typeof DIMENSION_LABELS)[]
          ).map((key) => (
            <div
              key={key}
              className="rounded-md border border-border bg-background p-3"
            >
              <div className="text-xs text-muted-foreground">
                {DIMENSION_LABELS[key]}
              </div>
              <div className="text-lg font-semibold">
                {grade.dimension_scores[key]}
                <span className="text-sm font-normal text-muted-foreground">
                  {" "}
                  / 6
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-medium">Overall comment</h3>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {grade.overall_comment}
        </p>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium">
          Corrections ({grade.corrections.length})
        </h3>
        {grade.corrections.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No corrections — nice work.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {grade.corrections.map((c, i) => (
              <li
                key={i}
                className="rounded-md border border-border bg-background p-3 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-destructive/10 px-1.5 py-0.5 text-destructive line-through">
                    {c.original}
                  </span>
                  <span className="text-muted-foreground">→</span>
                  <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-700">
                    {c.correction}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground">{c.explanation}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-start gap-4 p-8">
      {children}
    </main>
  );
}

function BackLink() {
  return (
    <Link
      href="/"
      className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
    >
      ← Back to questions
    </Link>
  );
}
