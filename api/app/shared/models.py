from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, Date, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.shared.database import Base


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auth / Profile
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    applications = relationship("Application", back_populates="user", lazy="dynamic")
    profile = relationship("Profile", back_populates="user", uselist=False)
    memories = relationship("AgentMemory", back_populates="user", lazy="dynamic")
    notifications = relationship("Notification", back_populates="user", lazy="dynamic")


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    full_name = Column(String(255))
    target_roles = Column(Text)           # JSON array
    target_locations = Column(Text)       # JSON array
    target_industries = Column(Text)      # JSON array
    years_experience = Column(Integer)
    skills = Column(Text)                 # JSON array
    resume_text = Column(Text)
    resume_html = Column(Text)
    linkedin_url = Column(String(500))
    # Search preferences
    remote_preference = Column(String(20), default="any")   # remote | hybrid | onsite | any
    employment_type = Column(String(20), default="any")     # full_time | contract | any
    salary_floor = Column(Integer)                          # minimum acceptable salary
    salary_currency = Column(String(10), default="USD")
    excluded_companies = Column(Text)                       # JSON array
    role_fit_json = Column(Text)                            # last RoleFitOutput as JSON
    seniority_level = Column(String(50))                    # kept for backward compat, no longer primary
    target_titles = Column(Text)                            # JSON array of inferred target job titles
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    user = relationship("User", back_populates="profile")


# ---------------------------------------------------------------------------
# Applications (pipeline)
# ---------------------------------------------------------------------------

class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    role_title = Column(String(255), nullable=False)
    job_description = Column(Text)
    jd_summary = Column(Text)             # Haiku-generated 200-token summary; used by all subsequent agents
    source_url = Column(String(1000))
    source = Column(String(100))          # linkedin | indeed | greenhouse | rss | manual
    status = Column(String(50), default="selected", index=True)
    # selected | applied | interviewing | offered | rejected | withdrawn | archived
    fit_score = Column(Float)             # 0.0–1.0
    deadline = Column(Date)
    applied_at = Column(Date)
    resume_version = Column(String(50))   # which resume version was used
    notes = Column(Text)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    user = relationship("User", back_populates="applications")
    drafts = relationship("Draft", back_populates="application", lazy="dynamic")
    agent_runs = relationship("AgentRun", back_populates="application", lazy="dynamic")


# ---------------------------------------------------------------------------
# Generated resumes
# ---------------------------------------------------------------------------

class GeneratedResume(Base):
    __tablename__ = "generated_resumes"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    resume_json    = Column(Text, nullable=False)
    created_at     = Column(DateTime(timezone=True), default=_now)
    updated_at     = Column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    agent_name = Column(String(100), nullable=False)
    reasoning_pattern = Column(String(50))  # react | plan_execute | reflexion | workflow
    status = Column(String(50), default="running")
    # running | complete | failed | waiting_for_human
    attempt_number = Column(Integer, default=1)
    system_prompt = Column(Text)
    final_output = Column(Text)           # structured JSON result
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cache_read_tokens = Column(Integer, default=0)
    cache_creation_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True), default=_now)
    completed_at = Column(DateTime(timezone=True))

    application = relationship("Application", back_populates="agent_runs")
    tool_calls = relationship("ToolCall", back_populates="agent_run", lazy="dynamic")


class AgentJob(Base):
    """Parallel job queue — one row per enqueued agent invocation."""
    __tablename__ = "agent_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=True, index=True)  # LangGraph session_id
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_name = Column(String(100), nullable=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    parent_job_id = Column(Integer, ForeignKey("agent_jobs.id"), nullable=True)
    reasoning_pattern = Column(String(50))
    status = Column(String(50), default="queued", index=True)
    # queued | running | waiting_for_human | complete | failed
    priority = Column(Integer, default=5)   # 1=urgent, 5=normal, 10=background
    params_json = Column(Text)              # input params as JSON
    result_json = Column(Text)              # final result or error JSON
    result_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))


class ToolCall(Base):
    """Every tool call made during any agent run."""
    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False, index=True)
    tool_use_id = Column(String(100), nullable=False)  # Claude's tool_use block id
    tool_name = Column(String(100), nullable=False)
    input_params_json = Column(Text, nullable=False)
    output_json = Column(Text)
    error = Column(Text)
    is_self_correction = Column(Boolean, default=False)
    iteration_number = Column(Integer, default=1)
    called_at = Column(DateTime(timezone=True), default=_now)
    duration_ms = Column(Integer)

    agent_run = relationship("AgentRun", back_populates="tool_calls")


class GraphCheckpoint(Base):
    """LangGraph state snapshots for pause-and-resume."""
    __tablename__ = "graph_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("agent_jobs.id"), nullable=True)
    node_name = Column(String(100), nullable=False)
    state_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    agent_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)
    draft_type = Column(String(100), nullable=False)
    # cover_letter | resume_edit | connect_msg | follow_up | interview_q | negotiation
    gate_tier = Column(String(20), default="soft")   # auto | soft | hard
    status = Column(String(50), default="pending")
    # pending | approved | edited | rejected
    content = Column(Text, nullable=False)
    user_edited_content = Column(Text)
    approved_at = Column(DateTime(timezone=True))
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)

    application = relationship("Application", back_populates="drafts")


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class AgentMemory(Base):
    __tablename__ = "agent_memory"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(255), nullable=False)   # dot-notation: user_preferences.X
    value = Column(Text, nullable=False)
    context = Column(Text)                       # e.g. "learned from resume_agent run 42"
    confidence = Column(Float, default=1.0)      # 0.0–1.0
    last_updated = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    user = relationship("User", back_populates="memories")


# ---------------------------------------------------------------------------
# Human gates
# ---------------------------------------------------------------------------

class PendingQuestion(Base):
    __tablename__ = "pending_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_job_id = Column(Integer, ForeignKey("agent_jobs.id"), nullable=True)
    agent_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)
    question = Column(Text, nullable=False)
    options_json = Column(Text)             # JSON array of option strings, or NULL for free text
    context_json = Column(Text)             # additional context to show user
    gate_tier = Column(String(20), default="hard")   # soft | hard
    urgency = Column(String(20), default="normal")   # low | normal | high | urgent
    expires_at = Column(DateTime(timezone=True))     # NULL for hard gates
    answered_at = Column(DateTime(timezone=True))
    answer = Column(Text)
    is_expired = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(100), nullable=False)
    # deadline_warning | follow_up_suggestion | new_match | company_news
    # pipeline_blocked | agent_update | pending_question
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    action_url = Column(String(500))
    gate_tier = Column(String(20))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    user = relationship("User", back_populates="notifications")


# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------

class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    query = Column(String(500), nullable=False)
    location = Column(String(255))
    sources_json = Column(Text)         # JSON array: ["linkedin", "indeed", "greenhouse"]
    last_run_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Audit log (hash-chained)
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=_now, nullable=False)
    event_type = Column(String(100), nullable=False)
    # agent_call | approval | rejection | status_change | login | error
    entity_type = Column(String(100))
    entity_id = Column(Integer)
    actor = Column(String(50), nullable=False)   # system | user
    payload = Column(Text, nullable=False)        # JSON
    content_hash = Column(String(64), nullable=False)
    prev_hash = Column(String(64), nullable=False)
    chain_hash = Column(String(64), nullable=False)


# ---------------------------------------------------------------------------
# Job feedback (relevant / not_relevant ratings on research results)
# ---------------------------------------------------------------------------

class JobFeedback(Base):
    __tablename__ = "job_feedback"
    __table_args__ = (UniqueConstraint("user_id", "job_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_url = Column(String(1000), nullable=False)
    job_title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    relevance = Column(String(20), nullable=False)   # relevant | not_relevant
    reason = Column(String(100), nullable=True)      # why not relevant — null for relevant
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Title skill map (required skills per target title, derived from JD keywords)
# ---------------------------------------------------------------------------

class TitleSkillMap(Base):
    __tablename__ = "title_skill_map"
    __table_args__ = (UniqueConstraint("user_id", "title"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    required_skills = Column(Text, nullable=False)   # JSON array
    source_keywords = Column(Text)                   # JSON array — raw JD keywords used to derive
    last_updated = Column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Job postings (auto-scraped, scored in background)
# ---------------------------------------------------------------------------

class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("user_id", "mcf_uuid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mcf_uuid = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    url = Column(String(1000), nullable=False)
    location = Column(String(255))
    description = Column(Text)
    inferred_industries = Column(Text)          # JSON array
    posted_at = Column(DateTime(timezone=True))
    scraped_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    # LLM scoring fields — null until scored
    scored = Column(Boolean, default=False, nullable=False, index=True)
    fit_score = Column(Float)
    reasons = Column(Text)                      # JSON array
    risks = Column(Text)                        # JSON array
    key_keywords = Column(Text)                 # JSON array
    scoring_breakdown = Column(Text)            # JSON array of ScoreCategory
    score_error = Column(Text)                  # set when scoring fails; scored stays 0
    scored_at = Column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------

class BudgetRecord(Base):
    __tablename__ = "budget_records"
    __table_args__ = (UniqueConstraint("date", "agent_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    agent_name = Column(String(100), nullable=False)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_cache_read_tokens = Column(Integer, default=0)
    total_cache_creation_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    call_count = Column(Integer, default=0)
