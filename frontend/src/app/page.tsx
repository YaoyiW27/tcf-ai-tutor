"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getQuestions, type Question } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "success"; questions: Question[] }
  | { kind: "error"; message: string };

export default function Home() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    getQuestions()
      .then((questions) => setState({ kind: "success", questions }))
      .catch((err) =>
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        }),
      );
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight">TCF Questions</h1>
        <p className="text-sm text-muted-foreground">
          Loaded from the backend at <code>GET /questions</code>.
        </p>
      </header>

      {state.kind === "loading" && (
        <p className="text-sm text-muted-foreground">Loading questions…</p>
      )}

      {state.kind === "error" && (
        <p className="text-sm text-destructive">
          Failed to load questions: {state.message}
        </p>
      )}

      {state.kind === "success" && state.questions.length === 0 && (
        <p className="text-sm text-muted-foreground">No questions yet.</p>
      )}

      {state.kind === "success" && state.questions.length > 0 && (
        <ul className="flex flex-col gap-4">
          {state.questions.map((q) => (
            <li key={q.id}>
              <Link
                href={`/questions/${q.id}`}
                className="block rounded-lg border border-border bg-card p-4 text-card-foreground transition-colors hover:border-foreground/30 hover:bg-accent"
              >
                <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="font-medium text-foreground">
                    Task {q.task_number}
                  </span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
                    {q.difficulty_level}
                  </span>
                  <span className="ml-auto text-xs">
                    {q.word_count_min}–{q.word_count_max} words
                  </span>
                </div>
                <p className="text-sm leading-relaxed">{q.prompt}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
