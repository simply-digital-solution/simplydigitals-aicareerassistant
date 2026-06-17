from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class AgentBaseModel(BaseModel):
    model_config = ConfigDict(strict=False, extra="ignore")


# ---------------------------------------------------------------------------
# Agent 1 — Role & Market Research
# ---------------------------------------------------------------------------

class ScoreRow(AgentBaseModel):
    category: str    # e.g. Technical, Experience, Education, Domain, Soft Skills
    requirement: str # specific JD requirement
    your_profile: str
    match: str       # free-form label, e.g. "✅ Exceeds", "❌ Critical gap"


class JobOpportunity(AgentBaseModel):
    job_id: int
    role: str
    company: str
    link: str
    fit_score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(min_length=1, max_length=5)
    risks: list[str] = Field(min_length=1, max_length=5)
    key_keywords: list[str] = Field(min_length=1, max_length=10)
    inferred_industries: list[str] = Field(default_factory=list)
    scoring_breakdown: list[ScoreRow] = Field(default_factory=list)
    recommendation: str = ""


class ResearchOutput(AgentBaseModel):
    opportunities: list[JobOpportunity]


# ---------------------------------------------------------------------------
# Industry Classifier (backfill tool)
# ---------------------------------------------------------------------------

class IndustryClassification(AgentBaseModel):
    job_id: int
    industries: list[str] = Field(default_factory=list)


class IndustryClassifierOutput(AgentBaseModel):
    classifications: list[IndustryClassification]


# ---------------------------------------------------------------------------
# Agent 2 — Resume & LinkedIn Optimizer
# ---------------------------------------------------------------------------

class LineEdit(AgentBaseModel):
    original: str
    suggested: str
    section: str   # summary | experience | skills | education


class ResumeOutput(AgentBaseModel):
    resume_edits: list[LineEdit]
    headline: str
    about_options: list[str] = Field(min_length=1, max_length=3)
    skills_reorder: list[str]
    suggested_metrics: list[str]
    # Rule: never invent metrics. Return "N/A" if not provided by user.


# ---------------------------------------------------------------------------
# Agent 2b — Resume Generator (full tailored resume)
# ---------------------------------------------------------------------------

class GeneratedResumeExperience(AgentBaseModel):
    title: str
    company: str
    dates: str
    bullets: list[str]


class GeneratedResumeSection(AgentBaseModel):
    section_type: str   # summary | experience | skills | education | other
    title: str          # heading as it appears in user's original resume
    content: list[str] = Field(default_factory=list)           # paragraphs or bullet points
    experience: list[GeneratedResumeExperience] = Field(default_factory=list)  # only for experience sections


class GeneratedResumeOutput(AgentBaseModel):
    name: str
    headline: str
    sections: list[GeneratedResumeSection]


# ---------------------------------------------------------------------------
# Agent 3 — Job Application Drafts
# ---------------------------------------------------------------------------

class ApplicationOutput(AgentBaseModel):
    cover_letter: str
    cv_tailor_notes: list[str]
    linkedin_note: str
    key_match_points: list[str]


# ---------------------------------------------------------------------------
# Agent 4 — Interview Coach
# ---------------------------------------------------------------------------

class BehaviouralQuestion(AgentBaseModel):
    q: str
    guidance: str


class TechnicalQuestion(AgentBaseModel):
    q: str
    answer_outline: str


class StarExample(AgentBaseModel):
    situation: str
    task: str
    action: str
    result: str
    applicable_questions: list[str]


class InterviewOutput(AgentBaseModel):
    behavioural: list[BehaviouralQuestion]
    technical: list[TechnicalQuestion]
    star_examples: list[StarExample]
    interviewer_questions: list[str]


# ---------------------------------------------------------------------------
# Agent 5 — Role Fit Advisor
# ---------------------------------------------------------------------------

class RoleSuggestion(AgentBaseModel):
    title: str
    tier: str   # strong | stretch | adjacent
    reasons: list[str] = Field(min_length=1, max_length=5)
    gaps: list[str] = Field(default_factory=list, max_length=5)
    key_skills: list[str] = Field(default_factory=list, max_length=8)
    gap_skills: list[str] = Field(default_factory=list, max_length=8)
    search_query: str


class RoleFitOutput(AgentBaseModel):
    candidate_summary: str
    seniority_level: str   # junior | mid | senior | lead | director | vp
    core_skills: list[str] = Field(min_length=1, max_length=20)
    roles: list[RoleSuggestion] = Field(min_length=3, max_length=12)


# ---------------------------------------------------------------------------
# Agent 6 — Learning & Signals Monitor
# ---------------------------------------------------------------------------

class MarketSignal(AgentBaseModel):
    category: str   # skill_trend | company_news | salary_data | hiring_signal
    title: str
    summary: str
    relevance: str
    source_hint: str


class SignalsOutput(AgentBaseModel):
    week_of: str
    signals: list[MarketSignal]
    recommended_learning: list[str]
    emerging_keywords: list[str]


# ---------------------------------------------------------------------------
# Generic error output (fallback when Claude can't produce valid JSON)
# ---------------------------------------------------------------------------

class AgentError(BaseModel):
    error: str
    raw_output: Optional[str] = None
    needs_human_review: bool = True
