import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-4xl font-semibold tracking-tight">
        Hello, TCF AI Tutor
      </h1>
      <p className="text-muted-foreground">
        Frontend scaffold: Next.js + Tailwind + shadcn/ui
      </p>
      <Button>Get started</Button>
    </main>
  );
}
