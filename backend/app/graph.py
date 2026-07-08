"""LangGraph grading pipeline.

The grader runs as a four-node pipeline so that *finding* errors and
*judging* them are separate steps — this is what stops the model from
"correcting" French that was already correct:

    START → score ──────┐
                        ├→ verify_errors → assemble → END
    START → find_errors ┘

``score`` and ``find_errors`` are independent and run concurrently; their
state writes are disjoint, so no channel reducer is needed. ``verify_errors``
fans in and only runs once BOTH have finished.

- ``score``          — four rubric dimensions + CEFR level + comment (no fixes)
- ``find_errors``    — over-collect candidate errors (recall over precision)
- ``verify_errors``  — keep only the candidates that are genuine errors
- ``assemble``       — combine scores + comment + verified errors into the
                       final ``EssayGrade`` (pure assembly, no Claude call)

Each LLM step is one structured Claude call living in :mod:`app.grader`; the
nodes here just thread state. The compiled graph is built once at import time
and reused for every request — do not recompile per call. Routers should
depend on :func:`run_grader` rather than touching the graph directly.
"""

import inspect
import logging
import time
from functools import wraps
from typing import TypedDict

from langfuse import Langfuse, get_client, observe
from langgraph.graph import END, START, StateGraph

from app import grader
from app.config import settings
from app.grader import Correction, EssayGrade
from app.models import Question

# Langfuse tracing for the grader. Keys live in .env, which pydantic-settings
# loads into `settings` (not os.environ), so the SDK can't auto-discover them —
# pass them explicitly, exactly like the Anthropic client. Initialised once at
# import only when both keys are present; otherwise tracing is disabled and the
# @observe()'d run_grader below runs unchanged.
if settings.langfuse_public_key and settings.langfuse_secret_key:
    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )

# Timing instrumentation only — one line per node + a total per run, so it's
# easy to see which step dominates the ~10–15s grade. Self-contained handler so
# the lines show up under uvicorn without depending on root logging config.
logger = logging.getLogger("app.graph")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _timed(name: str, fn):
    """Wrap a graph node so it logs ``[grade] <name> took N.Ns``.

    Preserves the node's sync/async nature and returns its result unchanged —
    pure instrumentation, no behavior change.
    """
    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(state: "GraphState") -> dict:
            start = time.perf_counter()
            try:
                return await fn(state)
            finally:
                logger.info("[grade] %s took %.1fs", name, time.perf_counter() - start)

        return async_wrapper

    @wraps(fn)
    def sync_wrapper(state: "GraphState") -> dict:
        start = time.perf_counter()
        try:
            return fn(state)
        finally:
            logger.info("[grade] %s took %.1fs", name, time.perf_counter() - start)

    return sync_wrapper


class GraphState(TypedDict):
    """State accumulated as the pipeline runs.

    ``question`` and ``content`` are the inputs. Each node fills in its
    slice; ``assemble`` reads them all back to produce ``result``.
    """

    question: Question
    content: str
    # produced by `score`
    dimension_scores: dict[str, float]
    estimated_level: str
    overall_comment: str
    # produced by `find_errors`
    draft_corrections: list[Correction]
    # produced by `verify_errors`
    verified_corrections: list[Correction]
    # produced by `assemble`
    result: EssayGrade


def _log_generation(name: str, usage) -> None:
    """Record one Anthropic call as a Langfuse generation under the current span.

    Nests under whichever node span is active (the ``@observe()``'d node that
    calls this), capturing the model and input/output token counts. No-op when
    tracing is disabled — ``get_client()`` returns a disabled stub then.
    """
    get_client().start_observation(
        name=name,
        as_type="generation",
        model=grader.MODEL,
        usage_details={
            "input": usage.input_tokens,
            "output": usage.output_tokens,
        },
    ).end()


@observe()
async def score_node(state: GraphState) -> dict:
    """Score the four dimensions + CEFR level + comment."""
    score, usage = await grader.score_essay(state["question"], state["content"])
    _log_generation("score", usage)
    return {
        "dimension_scores": {
            "task_fulfillment": score.task_fulfillment,
            "coherence": score.coherence,
            "vocabulary": score.vocabulary,
            "grammar": score.grammar,
        },
        "estimated_level": score.estimated_level,
        "overall_comment": score.overall_comment,
    }


@observe()
async def find_errors_node(state: GraphState) -> dict:
    """Over-collect candidate language errors."""
    draft, usage = await grader.find_errors(state["question"], state["content"])
    _log_generation("find_errors", usage)
    return {"draft_corrections": draft}


@observe()
async def verify_errors_node(state: GraphState) -> dict:
    """Filter the candidates down to genuine errors."""
    verified, usage = await grader.verify_errors(
        state["content"], state["draft_corrections"]
    )
    if usage is not None:
        _log_generation("verify_errors", usage)
    return {"verified_corrections": verified}


@observe()
def assemble_node(state: GraphState) -> dict:
    """Combine the pieces into the final EssayGrade (no Claude call).

    The NCLC level + écrite band are a pure-Python lookup from the model's
    estimated_level — no extra LLM call.
    """
    scores = state["dimension_scores"]
    nclc_level, ecrit_band = grader.nclc_band_for(state["estimated_level"])
    result = EssayGrade(
        task_fulfillment=scores["task_fulfillment"],
        coherence=scores["coherence"],
        vocabulary=scores["vocabulary"],
        grammar=scores["grammar"],
        estimated_level=state["estimated_level"],
        overall_comment=state["overall_comment"],
        corrections=state["verified_corrections"],
        nclc_level=nclc_level,
        ecrit_band=ecrit_band,
    )
    return {"result": result}


def _build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("score", _timed("score", score_node))
    builder.add_node("find_errors", _timed("find_errors", find_errors_node))
    builder.add_node("verify_errors", _timed("verify_errors", verify_errors_node))
    builder.add_node("assemble", _timed("assemble", assemble_node))
    # score and find_errors are independent: fan them out from START so they
    # run concurrently, then fan in to verify_errors (it waits for BOTH). Their
    # state writes are disjoint (see GraphState comments), so no channel reducer
    # is needed despite the parallel updates.
    builder.add_edge(START, "score")
    builder.add_edge(START, "find_errors")
    builder.add_edge("score", "verify_errors")
    builder.add_edge("find_errors", "verify_errors")
    builder.add_edge("verify_errors", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile()


# Compile once at import time; reused across requests.
_graph = _build_graph()


@observe()
async def run_grader(
    question: Question,
    content: str,
    *,
    user_id: str | None = None,
    question_id: str | None = None,
) -> EssayGrade:
    """Invoke the grading pipeline and return the validated :class:`EssayGrade`.

    Wrapped in Langfuse's ``@observe`` so each grade is one top-level trace
    (individual nodes are not instrumented yet — just this entry point).

    ``user_id`` / ``question_id`` (when supplied by the caller) plus the
    resulting CEFR level are attached to the trace as business dimensions so
    grades can be sliced per user / per question in Langfuse. Both ids are
    optional so the eval harness, which has neither, calls this unchanged.
    """
    langfuse = get_client()
    start = time.perf_counter()
    try:
        final_state = await _graph.ainvoke({"question": question, "content": content})
        logger.info("[grade] run_grader total took %.1fs", time.perf_counter() - start)
        result: EssayGrade = final_state["result"]
        # Attach business dimensions to this trace's root observation (the span
        # @observe() created for run_grader). The Langfuse 4.7.1 client has no
        # update_current_trace()/update_current_observation(); update_current_span()
        # is the available equivalent, and it only takes `metadata`, so user/question
        # ids and the CEFR level all go in the metadata dict. The ids are known up
        # front but the CEFR level only after the graph completes, so we set all
        # three in one call here. No-op when tracing is disabled.
        metadata: dict[str, str] = {"cefr_level": result.estimated_level}
        if user_id is not None:
            metadata["user_id"] = str(user_id)
        if question_id is not None:
            metadata["question_id"] = str(question_id)
        langfuse.update_current_span(metadata=metadata)
        return result
    finally:
        # Flush this run's trace once the graph has finished (success or error).
        # No-op when tracing is disabled.
        langfuse.flush()
