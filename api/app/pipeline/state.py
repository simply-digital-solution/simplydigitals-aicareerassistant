"""
LangGraph central state object.
Every graph node reads from and writes to this TypedDict.
Eliminates data-passing complexity between nodes.
"""
from typing import Optional, Any
from typing_extensions import TypedDict

from app.shared.schemas import (
    ResearchOutput, ResumeOutput, ApplicationOutput,
    InterviewOutput, SignalsOutput, AgentError,
)


class GraphState(TypedDict, total=False):
    # Session identity
    user_id: int
    session_id: str
    trigger: str              # "manual" | "scheduled" | "event"

    # User profile (loaded once at session start from profile.yaml)
    profile: dict[str, Any]

    # Target applications for this session
    target_app_ids: list[int]

    # Inputs passed to individual agents
    job_description: Optional[str]   # raw JD text for application/resume agents

    # Agent outputs
    research_result: Optional[ResearchOutput]
    resume_result: Optional[ResumeOutput]
    application_result: Optional[ApplicationOutput]
    interview_result: Optional[InterviewOutput]
    signals_result: Optional[SignalsOutput]

    # Error tracking
    errors: list[AgentError]

    # Human-gate tracking
    pending_draft_ids: list[int]     # draft IDs awaiting approval
    current_node: str                # last executed node name

    # Token budget (Phase 1: enforced; Phase 0: tracked only)
    token_budget_used: int
    token_budget_limit: int

    # Run metadata
    run_metadata: dict[str, Any]     # keyed by agent_name → meta dict from api_client
