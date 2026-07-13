"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAudioRecorder } from "@/lib/use-audio-recorder";
import {
  getQuestions,
  gradeSpeakingAnswer,
  submitSpeakingAnswer,
  type Question,
  type SpeakingGrade,
} from "@/lib/api";

type QuestionState =
  | { kind: "loading" }
  | { kind: "ready"; question: Question }
  | { kind: "notfound" }
  | { kind: "error"; message: string };

// Two backend steps behind one Submit: transcribe (STT), then grade. The
// transcript arrives after step 1 and is kept through grading/done so the user
// sees what Whisper heard.
type SubmitState =
  | { kind: "idle" }
  | { kind: "transcribing" }
  | { kind: "grading"; transcript: string }
  | { kind: "done"; transcript: string; grade: SpeakingGrade }
  | { kind: "error"; message: string; transcript?: string };

const DIMENSION_LABELS: Record<
  keyof SpeakingGrade["dimension_scores"],
  string
> = {
  grammar: "Grammar",
  coherence: "Coherence",
  lexis: "Lexis",
  task_fulfillment: "Task fulfillment",
};

function formatClock(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatTarget(totalSeconds: number): string {
  const minutes = totalSeconds / 60;
  return Number.isInteger(minutes)
    ? `${minutes} min`
    : `${minutes.toFixed(1)} min`;
}

export default function SpeakingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const [state, setState] = useState<QuestionState>({ kind: "loading" });
  const [submit, setSubmit] = useState<SubmitState>({ kind: "idle" });
  const recorder = useAudioRecorder();

  useEffect(() => {
    getQuestions()
      .then((questions) => {
        const question = questions.find((q) => q.id === id);
        setState(
          question && question.exam_section === "speaking"
            ? { kind: "ready", question }
            : { kind: "notfound" },
        );
      })
      .catch((err) =>
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        }),
      );
  }, [id]);

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
        <p className="text-sm text-muted-foreground">
          Speaking question not found.
        </p>
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
  const busy = submit.kind === "transcribing" || submit.kind === "grading";
  const transcript =
    submit.kind === "grading" || submit.kind === "done"
      ? submit.transcript
      : submit.kind === "error"
        ? submit.transcript
        : undefined;

  async function onSubmit() {
    if (!recorder.blob) return;
    setSubmit({ kind: "transcribing" });
    try {
      const answer = await submitSpeakingAnswer(
        question.id,
        recorder.blob,
        recorder.filename ?? "recording.webm",
      );
      setSubmit({ kind: "grading", transcript: answer.transcript });
      const grade = await gradeSpeakingAnswer(answer.id);
      setSubmit({ kind: "done", transcript: answer.transcript, grade });
    } catch (err) {
      setSubmit((prev) => ({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
        transcript: prev.kind === "grading" ? prev.transcript : undefined,
      }));
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
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
            Speaking
          </span>
          <span className="ml-auto text-xs">
            target ~{formatTarget(question.time_limit_seconds)}
          </span>
        </div>
        <h1 className="text-xl font-semibold leading-relaxed">
          {question.prompt}
        </h1>
        <p className="whitespace-pre-line text-sm text-muted-foreground">
          {question.instructions}
        </p>
      </header>

      <Recorder recorder={recorder} busy={busy} />

      {recorder.status === "recorded" && (
        <Button
          onClick={onSubmit}
          disabled={busy || !recorder.blob}
          className="self-start"
        >
          {submit.kind === "transcribing"
            ? "Transcribing…"
            : submit.kind === "grading"
              ? "Grading…"
              : "Submit for grading"}
        </Button>
      )}

      {submit.kind === "transcribing" && (
        <p className="text-sm text-muted-foreground">
          Transcribing your recording with Whisper…
        </p>
      )}
      {submit.kind === "grading" && (
        <p className="text-sm text-muted-foreground">
          Running the grader — three AI passes (score → find errors → verify).
          Please keep this tab open.
        </p>
      )}

      {transcript !== undefined && <TranscriptPanel transcript={transcript} />}

      {submit.kind === "error" && (
        <p className="text-sm text-destructive">
          Something went wrong: {submit.message}
        </p>
      )}

      {submit.kind === "done" && <SpeakingGradeReport grade={submit.grade} />}
    </main>
  );
}

function Recorder({
  recorder,
  busy,
}: {
  recorder: ReturnType<typeof useAudioRecorder>;
  busy: boolean;
}) {
  if (recorder.status === "unsupported") {
    return (
      <section className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
        Audio recording isn’t supported in this browser. Try a recent version
        of Chrome, Edge, Firefox, or Safari.
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-5">
      <div className="flex items-center gap-3">
        {recorder.status === "recording" ? (
          <Button variant="destructive" onClick={recorder.stop}>
            ■ Stop recording
          </Button>
        ) : recorder.status === "recorded" ? (
          <Button variant="outline" onClick={recorder.reset} disabled={busy}>
            ↺ Re-record
          </Button>
        ) : (
          <Button
            onClick={recorder.start}
            disabled={recorder.status === "requesting" || busy}
          >
            ● {recorder.status === "requesting" ? "Requesting mic…" : "Record"}
          </Button>
        )}

        {recorder.status === "recording" && (
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="size-2 animate-pulse rounded-full bg-destructive" />
            {formatClock(recorder.seconds)}
          </span>
        )}
      </div>

      {recorder.status === "recorded" && recorder.url && (
        <audio controls src={recorder.url} className="w-full">
          Your browser does not support audio playback.
        </audio>
      )}

      {recorder.error && (
        <p className="text-sm text-destructive">{recorder.error}</p>
      )}
    </section>
  );
}

function TranscriptPanel({ transcript }: { transcript: string }) {
  return (
    <section className="flex flex-col gap-1 rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-medium">Transcript</h3>
      <p className="text-xs text-muted-foreground">
        What Whisper heard — grading is based on this text (pronunciation isn’t
        assessed).
      </p>
      <p className="mt-1 text-sm leading-relaxed">
        {transcript.trim() === "" ? (
          <span className="text-muted-foreground">
            (No speech was detected in the recording.)
          </span>
        ) : (
          transcript
        )}
      </p>
    </section>
  );
}

function SpeakingGradeReport({ grade }: { grade: SpeakingGrade }) {
  return (
    <section className="flex flex-col gap-5 rounded-lg border border-border bg-card p-5">
      {/* Headline: estimated level + NCLC + expression orale band. */}
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
          {grade.oral_band && (
            <span className="text-sm text-muted-foreground">
              Expression orale{" "}
              <span className="font-semibold text-foreground">
                {grade.oral_band === "below 6" ? "non atteint" : grade.oral_band}
              </span>
              {grade.oral_band !== "below 6" && " / 20"}
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
          <p className="text-sm text-muted-foreground">No corrections</p>
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
