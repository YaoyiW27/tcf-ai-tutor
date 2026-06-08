"""LangGraph grading pipeline.

The grader runs as a four-node pipeline so that *finding* errors and
*judging* them are separate steps — this is what stops the model from
"correcting" French that was already correct:

    START → score → find_errors → verify_errors → assemble → END

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

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app import grader
from app.grader import Correction, EssayGrade
from app.models import Question


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


async def score_node(state: GraphState) -> dict:
    """Score the four dimensions + CEFR level + comment."""
    score = await grader.score_essay(state["question"], state["content"])
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


async def find_errors_node(state: GraphState) -> dict:
    """Over-collect candidate language errors."""
    draft = await grader.find_errors(state["question"], state["content"])
    return {"draft_corrections": draft}


async def verify_errors_node(state: GraphState) -> dict:
    """Filter the candidates down to genuine errors."""
    verified = await grader.verify_errors(state["content"], state["draft_corrections"])
    return {"verified_corrections": verified}


def assemble_node(state: GraphState) -> dict:
    """Combine the pieces into the final EssayGrade (no Claude call)."""
    scores = state["dimension_scores"]
    result = EssayGrade(
        task_fulfillment=scores["task_fulfillment"],
        coherence=scores["coherence"],
        vocabulary=scores["vocabulary"],
        grammar=scores["grammar"],
        estimated_level=state["estimated_level"],
        overall_comment=state["overall_comment"],
        corrections=state["verified_corrections"],
    )
    return {"result": result}


def _build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("score", score_node)
    builder.add_node("find_errors", find_errors_node)
    builder.add_node("verify_errors", verify_errors_node)
    builder.add_node("assemble", assemble_node)
    builder.add_edge(START, "score")
    builder.add_edge("score", "find_errors")
    builder.add_edge("find_errors", "verify_errors")
    builder.add_edge("verify_errors", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile()


# Compile once at import time; reused across requests.
_graph = _build_graph()


async def run_grader(question: Question, content: str) -> EssayGrade:
    """Invoke the grading pipeline and return the validated :class:`EssayGrade`."""
    final_state = await _graph.ainvoke({"question": question, "content": content})
    return final_state["result"]
