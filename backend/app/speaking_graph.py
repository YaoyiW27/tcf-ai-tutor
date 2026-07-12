"""LangGraph grading pipeline for TCF Speaking transcripts.

A direct mirror of :mod:`app.graph` (the Writing grader), operating on a
transcript instead of an essay:

    START → score ──────┐
                        ├→ verify_errors → assemble → END
    START → find_errors ┘

``score`` and ``find_errors`` are independent and run concurrently; their state
writes are disjoint, so no channel reducer is needed. ``verify_errors`` fans in
and only runs once BOTH have finished.

- ``score``          — four oral rubric dimensions + CEFR level + comment
- ``find_errors``    — over-collect candidate errors (recall over precision)
- ``verify_errors``  — keep only genuine errors (reuses the Writing judge)
- ``assemble``       — combine into the final ``SpeakingGrade`` (no Claude call)

Each LLM step lives in :mod:`app.speaking_grader`; the nodes here just thread
state. The compiled graph is built once at import time. Routers should depend on
:func:`run_speaking_grader` rather than touching the graph directly.
"""

import inspect
import logging
import time
from functools import wraps
from typing import TypedDict

from langfuse import get_client, observe
from langgraph.graph import END, START, StateGraph

from app import speaking_grader
from app.grader import Correction
from app.models import Question
from app.speaking_grader import SpeakingGrade

# Langfuse is initialised once in app.graph at import time (keys from settings).
# Importing it here would re-run that; instead we rely on app.graph having been
# imported by the app, and just use get_client() — a disabled stub when tracing
# is off. Import app.graph for its side-effect of configuring the client.
from app import graph  # noqa: F401  (ensures the Langfuse client is initialised)

# Timing instrumentation only — one line per node + a total per run. Separate
# logger/prefix from the Writing grader so Speaking timings are distinguishable.
logger = logging.getLogger("app.speaking_graph")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _timed(name: str, fn):
    """Wrap a graph node so it logs ``[speak] <name> took N.Ns``.

    Preserves the node's sync/async nature and returns its result unchanged.
    """
    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(state: "GraphState") -> dict:
            start = time.perf_counter()
            try:
                return await fn(state)
            finally:
                logger.info("[speak] %s took %.1fs", name, time.perf_counter() - start)

        return async_wrapper

    @wraps(fn)
    def sync_wrapper(state: "GraphState") -> dict:
        start = time.perf_counter()
        try:
            return fn(state)
        finally:
            logger.info("[speak] %s took %.1fs", name, time.perf_counter() - start)

    return sync_wrapper


class GraphState(TypedDict):
    """State accumulated as the pipeline runs.

    ``question`` and ``transcript`` are the inputs. Each node fills in its
    slice; ``assemble`` reads them all back to produce ``result``.
    """

    question: Question
    transcript: str
    # produced by `score`
    dimension_scores: dict[str, float]
    estimated_level: str
    overall_comment: str
    # produced by `find_errors`
    draft_corrections: list[Correction]
    # produced by `verify_errors`
    verified_corrections: list[Correction]
    # produced by `assemble`
    result: SpeakingGrade


def _log_generation(name: str, usage) -> None:
    """Record one Anthropic call as a Langfuse generation under the current span.

    No-op when tracing is disabled — ``get_client()`` returns a disabled stub.
    """
    get_client().start_observation(
        name=name,
        as_type="generation",
        model=speaking_grader.MODEL,
        usage_details={
            "input": usage.input_tokens,
            "output": usage.output_tokens,
        },
    ).end()


@observe()
async def score_node(state: GraphState) -> dict:
    """Score the four oral dimensions + CEFR level + comment."""
    score, usage = await speaking_grader.score_speaking(
        state["question"], state["transcript"]
    )
    _log_generation("score", usage)
    return {
        "dimension_scores": {
            "task_fulfillment": score.task_fulfillment,
            "coherence": score.coherence,
            "lexis": score.lexis,
            "grammar": score.grammar,
        },
        "estimated_level": score.estimated_level,
        "overall_comment": score.overall_comment,
    }


@observe()
async def find_errors_node(state: GraphState) -> dict:
    """Over-collect candidate language errors from the transcript."""
    draft, usage = await speaking_grader.find_errors(
        state["question"], state["transcript"]
    )
    _log_generation("find_errors", usage)
    return {"draft_corrections": draft}


@observe()
async def verify_errors_node(state: GraphState) -> dict:
    """Filter the candidates down to genuine errors (shared Writing judge)."""
    verified, usage = await speaking_grader.verify_errors(
        state["transcript"], state["draft_corrections"]
    )
    if usage is not None:
        _log_generation("verify_errors", usage)
    return {"verified_corrections": verified}


@observe()
def assemble_node(state: GraphState) -> dict:
    """Combine the pieces into the final SpeakingGrade (no Claude call).

    The NCLC level + oral band are a pure-Python lookup from the model's
    estimated_level — no extra LLM call.
    """
    scores = state["dimension_scores"]
    nclc_level, oral_band = speaking_grader.nclc_oral_band_for(state["estimated_level"])
    result = SpeakingGrade(
        task_fulfillment=scores["task_fulfillment"],
        coherence=scores["coherence"],
        lexis=scores["lexis"],
        grammar=scores["grammar"],
        estimated_level=state["estimated_level"],
        overall_comment=state["overall_comment"],
        corrections=state["verified_corrections"],
        nclc_level=nclc_level,
        oral_band=oral_band,
    )
    return {"result": result}


def _build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("score", _timed("score", score_node))
    builder.add_node("find_errors", _timed("find_errors", find_errors_node))
    builder.add_node("verify_errors", _timed("verify_errors", verify_errors_node))
    builder.add_node("assemble", _timed("assemble", assemble_node))
    # score and find_errors are independent: fan them out from START so they run
    # concurrently, then fan in to verify_errors (it waits for BOTH). Disjoint
    # state writes → no channel reducer needed.
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
async def run_speaking_grader(
    question: Question,
    transcript: str,
    *,
    user_id: str | None = None,
    question_id: str | None = None,
) -> SpeakingGrade:
    """Invoke the speaking pipeline and return the validated ``SpeakingGrade``.

    Wrapped in Langfuse's ``@observe`` so each grade is one top-level trace.
    ``user_id`` / ``question_id`` (when supplied) plus the resulting CEFR level
    are attached to the trace as business dimensions — same pattern as the
    Writing grader. Both ids are optional so the eval harness calls this
    unchanged.
    """
    langfuse = get_client()
    start = time.perf_counter()
    try:
        final_state = await _graph.ainvoke(
            {"question": question, "transcript": transcript}
        )
        logger.info(
            "[speak] run_speaking_grader total took %.1fs",
            time.perf_counter() - start,
        )
        result: SpeakingGrade = final_state["result"]
        # Business dimensions on the trace's root span (Langfuse 4.7.1 has no
        # update_current_trace(); update_current_span(metadata=...) is the
        # available equivalent). ids known up front, CEFR only after the graph.
        metadata: dict[str, str] = {"cefr_level": result.estimated_level}
        if user_id is not None:
            metadata["user_id"] = str(user_id)
        if question_id is not None:
            metadata["question_id"] = str(question_id)
        langfuse.update_current_span(metadata=metadata)
        return result
    finally:
        # Flush once the graph finishes (success or error). No-op when disabled.
        langfuse.flush()
