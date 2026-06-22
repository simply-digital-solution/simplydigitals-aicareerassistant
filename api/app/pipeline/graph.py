"""
LangGraph graph — Phase 0.

Linear workflow:
  load_profile → research → resume → END

Human gates are handled outside the graph in Phase 0
(user reviews drafts via the /approvals API).
Phase 1 will add parallel fan-out, ask_user gates, and orchestrator routing.
"""
import uuid
from typing import Any, Optional

from langgraph.graph import StateGraph, END

from app.pipeline.state import GraphState
from app.modules.agents.research_agent import run_research_agent
from app.modules.agents.resume_agent import run_resume_agent


# ---------------------------------------------------------------------------
# Node: load_profile
# ---------------------------------------------------------------------------

def load_profile(state: GraphState) -> GraphState:
    return {**state, "profile": {}, "current_node": "load_profile"}


# ---------------------------------------------------------------------------
# Node: run_research
# ---------------------------------------------------------------------------

async def run_research(state: GraphState) -> GraphState:
    """Runs the research agent against job_postings in state."""
    job_postings: list[dict] = state.get("run_metadata", {}).get("job_postings", [])
    if not job_postings:
        return {**state, "current_node": "run_research"}

    result, meta = await run_research_agent(
        profile=state.get("profile", {}),
        job_postings=job_postings,
        user_id=state.get("user_id"),
    )

    run_metadata = {**state.get("run_metadata", {}), "research": meta}
    errors = list(state.get("errors", []))

    from app.shared.schemas import AgentError
    if isinstance(result, AgentError):
        errors.append(result)
        return {**state, "errors": errors, "run_metadata": run_metadata, "current_node": "run_research"}

    return {
        **state,
        "research_result": result,
        "run_metadata": run_metadata,
        "errors": errors,
        "current_node": "run_research",
    }


# ---------------------------------------------------------------------------
# Node: run_resume
# ---------------------------------------------------------------------------

async def run_resume(state: GraphState) -> GraphState:
    """Runs the resume optimizer for the first target application."""
    profile = state.get("profile", {})
    resume_text = profile.get("background", {}).get("experience_summary", "")
    jd_text = state.get("job_description", "")

    if not jd_text:
        return {**state, "current_node": "run_resume"}

    result, meta = await run_resume_agent(
        profile=profile,
        resume_text=resume_text,
        jd_text=jd_text,
        user_id=state.get("user_id"),
    )

    run_metadata = {**state.get("run_metadata", {}), "resume": meta}
    errors = list(state.get("errors", []))

    from app.shared.schemas import AgentError
    if isinstance(result, AgentError):
        errors.append(result)
        return {**state, "errors": errors, "run_metadata": run_metadata, "current_node": "run_resume"}

    return {
        **state,
        "resume_result": result,
        "run_metadata": run_metadata,
        "errors": errors,
        "current_node": "run_resume",
    }


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("load_profile", load_profile)
    builder.add_node("run_research", run_research)
    builder.add_node("run_resume", run_resume)

    builder.set_entry_point("load_profile")
    builder.add_edge("load_profile", "run_research")
    builder.add_edge("run_research", "run_resume")
    builder.add_edge("run_resume", END)

    return builder.compile()


# Singleton compiled graph
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_session(
    user_id: int,
    job_postings: Optional[list[dict]] = None,
    job_description: Optional[str] = None,
    trigger: str = "manual",
) -> GraphState:
    """Entry point for triggering a graph session."""
    graph = get_graph()
    initial_state: GraphState = {
        "user_id": user_id,
        "session_id": str(uuid.uuid4()),
        "trigger": trigger,
        "profile": {},
        "target_app_ids": [],
        "job_description": job_description,
        "errors": [],
        "pending_draft_ids": [],
        "current_node": "",
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "run_metadata": {"job_postings": job_postings or []},
    }
    return await graph.ainvoke(initial_state)
