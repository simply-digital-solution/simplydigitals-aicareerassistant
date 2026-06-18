from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl


class ApplicationCreate(BaseModel):
    company_name: str
    role_title: str
    job_description: Optional[str] = None
    source_url: Optional[str] = None
    source: Optional[str] = "manual"
    status: Optional[str] = "selected"
    deadline: Optional[date] = None
    notes: Optional[str] = None
    job_posting_id: Optional[int] = None


class ApplicationUpdate(BaseModel):
    company_name: Optional[str] = None
    role_title: Optional[str] = None
    job_description: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[date] = None
    applied_at: Optional[date] = None
    notes: Optional[str] = None
    fit_score: Optional[float] = None


class ApplicationResponse(BaseModel):
    id: int
    user_id: int
    company_name: str
    role_title: str
    job_description: Optional[str]
    jd_summary: Optional[str]
    source_url: Optional[str]
    source: Optional[str]
    status: str
    fit_score: Optional[float]
    deadline: Optional[date]
    applied_at: Optional[date]
    notes: Optional[str]
    job_posting_id: Optional[int]
    status_updated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineMoveRequest(BaseModel):
    application_id: int
    new_status: str
