"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: unknown }
  | { kind: "error"; message: string };

export default function Home() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function checkBackend() {
    setStatus({ kind: "loading" });
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/health`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setStatus({ kind: "success", data });
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-4xl font-semibold tracking-tight">
        Hello, TCF AI Tutor
      </h1>
      <p className="text-muted-foreground">
        Frontend scaffold: Next.js + Tailwind + shadcn/ui
      </p>
      <Button onClick={checkBackend} disabled={status.kind === "loading"}>
        {status.kind === "loading" ? "Checking…" : "Check backend"}
      </Button>

      {status.kind === "success" && (
        <pre className="rounded-md bg-muted px-4 py-2 text-sm">
          {JSON.stringify(status.data, null, 2)}
        </pre>
      )}
      {status.kind === "error" && (
        <p className="text-sm text-destructive">Error: {status.message}</p>
      )}
    </main>
  );
}
