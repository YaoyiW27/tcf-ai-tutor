# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This is a **pre-implementation scaffold**. As of this file's writing, the repo contains only `README.md`, `LICENSE`, and `.gitignore` — no source code, no package manifest, no build/test tooling. Do not invent build, lint, or test commands; there are none yet. When implementation begins, update this file with the real commands.

The `.gitignore` is the Node/JS default (covers Next.js, Vite, pnpm, yarn, etc.), which hints at a likely Node-based frontend later — but no stack choice has been committed to in code yet.

## Project intent

A personal learning project: a **multi-agent AI tutor for TCF Canada** (French proficiency test) preparation. The primary goal is hands-on experience with AI engineering — multi-agent orchestration, voice AI, and LLM observability. TCF prep is the secondary, motivating use case.

Planned phases (see README "Status"):
1. Schema design & first agent
2. Writing AI Grader
3. Speaking Voice Agent
4. Multi-agent orchestration with LangGraph
5. Observability (Langfuse + OpenTelemetry)
6. Containerization & deployment

Planned stack: **LangGraph** (orchestration), **Whisper** (STT), **OpenAI / Anthropic** (LLM), **Langfuse** + **OpenTelemetry** (tracing), **Docker**. None of these are wired up yet.

## Scope guardrails

The README is explicit about what this project is *not*, and these constraints should shape suggestions:

- **Not a complete TCF question bank** — don't propose building out exhaustive content/data sets.
- **Not a replacement for PrepMyFrench** — don't optimize for product-market fit or end-user polish.
- **Not a startup or product play** — favor solutions that maximize learning (e.g., observability, tracing, multi-agent patterns) over solutions that maximize shipping speed.

The positioning is explicitly **AI engineering + DevOps/SRE practices applied to LLM systems**. When making architectural choices, prefer ones that exercise that intersection (containers, tracing, structured evals) over ones that just "get a chatbot working."
