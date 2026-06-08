"""LangGraph wrapper around the essay grader.

This is the first, deliberately trivial, LangGraph: a single ``grade`` node
that calls the existing :func:`app.grader.grade_essay` (one structured Claude
call) and writes its result into the graph state. It changes no grading
behaviour — it only proves the orchestration layer runs end to end, so later
phases (multi-agent, observability) have something to build on.

The compiled graph is built once at import time and reused for every request;
do not recompile per call. Routers should depend on :func:`run_grader` rather
than touching the graph directly.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app import grader
from app.grader import EssayGrade
from app.models import Question


class GraphState(TypedDict):
    """State threaded through the grading graph.

    ``question`` and ``content`` are the inputs; ``grade_node`` fills in
    ``result`` with the validated :class:`EssayGrade`.
    """

    question: Question
    content: str
    result: EssayGrade


async def grade_node(state: GraphState) -> dict:
    """Run the existing grader and stash the result in state."""
    grade = await grader.grade_essay(state["question"], state["content"])
    return {"result": grade}


def _build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("grade", grade_node)
    builder.add_edge(START, "grade")
    builder.add_edge("grade", END)
    return builder.compile()


# Compile once at import time; reused across requests.
_graph = _build_graph()


async def run_grader(question: Question, content: str) -> EssayGrade:
    """Invoke the grading graph and return the validated :class:`EssayGrade`."""
    final_state = await _graph.ainvoke({"question": question, "content": content})
    return final_state["result"]
