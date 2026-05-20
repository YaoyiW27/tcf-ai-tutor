# tcf-ai-tutor

A personal project to learn AI engineering by building a multi-agent
AI tutor for TCF Canada preparation.

## Goal

Primary: Gain hands-on experience with modern AI engineering — multi-agent
systems, voice AI, and production observability for LLM applications.

Secondary: Use it myself to prepare for TCF Canada.

## What it is (and isn't)

**Is:**
- A multi-agent system that helps with TCF Writing and Speaking practice
- A learning project for AI infrastructure and observability
- A bridge project: applying DevOps/SRE practices (containers, tracing,
  monitoring) to LLM systems

**Isn't:**
- A complete TCF question bank
- A replacement for PrepMyFrench
- A startup or product play

## Status

- [x] Project scaffold
- [ ] Phase 1: Schema design & first agent
- [ ] Phase 2: Writing AI Grader
- [ ] Phase 3: Speaking Voice Agent
- [ ] Phase 4: Multi-agent orchestration with LangGraph
- [ ] Phase 5: Observability (Langfuse + OpenTelemetry)
- [ ] Phase 6: Containerization & deployment

## Stack (planned)

**AI:**
- LangGraph — multi-agent orchestration
- Whisper — speech-to-text
- OpenAI / Anthropic API — LLM backbone

**Observability:**
- Langfuse — LLM-specific tracing (prompts, costs, latency)
- OpenTelemetry — distributed tracing across services

**Infrastructure:**
- Docker — containerization
- TBD: cloud deployment, frontend, database

## Positioning

This project sits at the intersection of AI engineering and DevOps —
showing how production engineering practices translate to LLM systems.