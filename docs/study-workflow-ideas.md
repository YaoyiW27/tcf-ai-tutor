# Study Workflow Ideas

Status: Idea bank
Date: 2026-06-17
Purpose: Use the TCF AI Tutor as a practical lab for learning multi-agent systems, evaluation, observability, and AI system security.

This document records possible learning experiments. It is not a promise to implement every item, and it should not replace the short-term tasks in `dev-log.md`.

## Guiding question

> Does a role-specialized multi-agent architecture improve French writing feedback quality enough to justify its additional latency, token usage, cost, and operational complexity?

The goal is not to add as many agents as possible. Each architectural change should answer a specific question and be compared against a simpler baseline.

## Current baseline

The writing grader is currently a fixed LangGraph workflow:

```text
START
├── score
└── find_errors
        ↓
   verify_errors
        ↓
     assemble
        ↓
       END
```

It already provides useful foundations for agent-system experiments:

- Shared LangGraph state
- Fan-out / fan-in parallel execution
- Multiple structured LLM calls
- A verification step that rejects false corrections
- Langfuse traces, generations, latency, and token usage
- A small regression eval suite

This is an agentic workflow, but not yet a strong multi-agent system. The nodes do not have independent goals or memory, routing is mostly fixed, and collaboration is limited.

## Proposed learning path

### Stage 1: Make the baseline measurable

Before adding more agents, improve the grader eval tool so experiments can be compared consistently.

- Select and list individual eval cases from the CLI
- Record pass/fail, latency, and failed case names
- Grow a small, curated eval set for false corrections and missed errors
- Keep cases human-readable and tied to known grader failure modes
- Record model and prompt versions when results become difficult to compare

This stage supports every later experiment.

### Stage 2: Add one Critic Agent

The smallest meaningful collaboration experiment is a Critic Agent that reviews proposed corrections before final feedback is assembled.

```text
score ───────────────┐
                    ├── critic ── assemble
find_errors ─ verify┘
```

The critic should:

- Inspect the original answer and proposed corrections
- Reject false positives and unnecessary stylistic rewrites
- Flag contradictions between the score and corrections
- Return structured decisions with short reasons

Compare the baseline and critic versions using the same eval cases. This tests reviewer/reflection patterns without immediately multiplying the number of agents.

### Stage 3: Role-specialized Agents

Split evaluation responsibilities only when the eval set shows that specialization may help:

- **Grammar Agent**: grammar, tense, gender, and number agreement
- **Vocabulary Agent**: word choice, precision, and naturalness
- **Coherence Agent**: structure, transitions, and logical flow
- **Task Agent**: task fulfillment, register, and format constraints
- **Critic Agent**: challenges unsupported or conflicting findings
- **Tutor Agent**: turns accepted findings into learner-friendly feedback

Possible architecture:

```text
Student answer
      ↓
  Supervisor
  ├── Grammar Agent ────┐
  ├── Vocabulary Agent ─┤
  ├── Coherence Agent ──┼── Critic Agent ── Tutor Agent
  └── Task Agent ───────┘
```

This stage should compare three architectures:

1. Single LLM call
2. Current fixed workflow
3. Role-specialized multi-agent workflow

### Stage 4: Supervisor and dynamic routing

Add a Supervisor only after specialized agents have clear responsibilities.

Example routing rules:

- Short beginner answer: Grammar + Task
- Longer advanced answer: Grammar + Vocabulary + Coherence + Task
- Conflicting agent findings: Critic
- High-confidence agreement: skip extra review

Learning topics:

- Conditional edges
- Dynamic routing
- Agent handoffs
- Confidence thresholds
- Retry and termination conditions
- Cost-aware routing

The Supervisor should reduce unnecessary model calls rather than merely add another one.

### Stage 5: Tools and learner memory

Agents can eventually use tools instead of relying only on model knowledge:

- TCF rubric retrieval
- French dictionary or grammar-rule lookup
- Student error-history search
- Long-term learner profile
- Practice generation based on recurring weak areas

Memory experiments should distinguish:

- Session memory: context from the current practice session
- Learning history: recurring mistakes and progress over time
- System memory: rubrics, examples, and verified language rules

Personal learner data should be minimized, access-controlled, and excluded from logs unless needed.

## Evaluation plan

For each architectural experiment, record:

- Correction precision: how many proposed corrections are genuinely useful
- False correction count
- Missed obvious error count
- Level-estimation accuracy or human agreement
- Task-fulfillment assessment quality
- Agent disagreement rate
- Output stability across repeated runs
- End-to-end latency
- Token usage and estimated cost
- Failure and timeout rate

Useful comparisons:

- Baseline vs Critic Agent
- Fixed workflow vs Supervisor routing
- All agents vs selectively routed agents
- One model for all roles vs cheaper models for narrow roles

Results should be stored as small experiment notes, not only screenshots.

## Observability experiments

Use Langfuse and later OpenTelemetry to make the workflow explainable:

- One trace per grading request
- One span or generation per agent
- Agent role, prompt version, model, and route as metadata
- Token usage and latency per agent
- Critic accept/reject decisions
- Disagreement and retry counts
- Trace links from stored feedback where appropriate

This makes it possible to explain not only whether a workflow performed better, but why it was slower, more expensive, or less stable.

## Security pipeline and scanning

Security should be part of the learning workflow rather than a final deployment checkbox.

### CI security checks

Possible pipeline stages:

- Secret scanning to prevent API keys from entering Git history
- Python dependency vulnerability scanning
- Node dependency vulnerability scanning
- Static application security testing for Python and TypeScript
- Container image scanning after Docker is introduced
- Infrastructure and Kubernetes manifest scanning in the deployment phase
- Software bill of materials generation for release artifacts

Candidate tools can be chosen when the pipeline is implemented. The important learning goal is to understand what each check detects, its false positives, and where it belongs in CI.

### AI-specific security experiments

- Prompt-injection attempts inside student answers
- Instructions that try to override the grading rubric
- Malformed or oversized input
- Sensitive-data leakage into prompts, traces, or feedback
- Unsafe tool access when retrieval and memory are added
- Untrusted retrieved content influencing agent behavior
- Output-schema validation and fail-closed behavior
- Rate limits, timeouts, and model-call budget limits

Security eval cases can eventually live beside quality eval cases so regressions are visible.

## Suggested implementation order

1. Grader Eval v1 CLI and clearer reporting
2. Expand the curated baseline eval set
3. Add Critic Agent behind an experiment flag
4. Compare baseline vs critic using quality, latency, and token metrics
5. Add Langfuse metadata for routes and experiment versions
6. Add initial CI secret and dependency scanning
7. Experiment with specialized agents and Supervisor routing
8. Add tools, learner memory, and their security controls
9. Container and deployment scanning

## Resume story

If developed with measured experiments, this project can demonstrate:

- LangGraph orchestration and dynamic routing
- Structured LLM outputs and multi-agent review patterns
- Regression eval design for nondeterministic systems
- Langfuse/OpenTelemetry observability
- Latency, quality, and cost trade-off analysis
- CI/CD security scanning and AI-specific threat testing
- Practical product use through TCF writing and speaking practice

The strongest story is not "I built many agents." It is "I measured when additional agents improved quality, what they cost, and how I operated the system safely."
