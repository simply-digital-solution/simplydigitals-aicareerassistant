from datetime import date, datetime

from pydantic import BaseModel


class ApplicationCreate(BaseModel):
    company_name: str
    role_title: str
    job_description: str | None = None
    source_url: str | None = None
    source: str | None = "manual"
    status: str | None = "selected"
    deadline: date | None = None
    notes: str | None = None
    job_posting_id: int | None = None


class ApplicationUpdate(BaseModel):
    company_name: str | None = None
    role_title: str | None = None
    job_description: str | None = None
    status: str | None = None
    deadline: date | None = None
    applied_at: date | None = None
    notes: str | None = None
    fit_score: float | None = None


class ApplicationResponse(BaseModel):
    id: int
    user_id: int
    company_name: str
    role_title: str
    job_description: str | None
    jd_summary: str | None
    source_url: str | None
    source: str | None
    status: str
    fit_score: float | None
    deadline: date | None
    applied_at: date | None
    notes: str | None
    job_posting_id: int | None
    status_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineMoveRequest(BaseModel):
    application_id: int
    new_status: str
