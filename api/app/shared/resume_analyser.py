"""
Single-pass resume analyser.

Runs all extraction in one call:
  years_experience, seniority_level, industries, skills

Each extractor reads the same resume_text — no redundant DB reads or
separate API calls needed.
"""
import re
from datetime import date
from typing import Optional

from app.shared.skill_extractor import extract_skill_names
from app.shared.seniority_extractor import extract_seniority
from app.shared.industry_extractor import extract_industries


def _estimate_years_experience(resume_text: str) -> Optional[int]:
    years = [int(y) for y in re.findall(r'\b(19[7-9]\d|20[0-3]\d)\b', resume_text)]
    if len(years) < 2:
        return None
    current_year = date.today().year
    earliest = min(years)
    latest = min(max(years), current_year)
    span = latest - earliest
    return max(1, span) if span > 0 else None


def analyse_resume(resume_text: str) -> dict:
    """
    Extract all profile fields derivable from resume text in one pass.
    Title extraction is excluded here — it's async (LLM-based) and handled
    separately in the router via extract_target_titles().

    Returns:
        years_experience : int | None
        seniority_level  : str          e.g. "senior"
        seniority_method : str          "keyword" | "bert" | "yoe_fallback"
        industries       : list[str]    e.g. ["Banking & Financial Services"]
        skills           : list[str]    e.g. ["Python", "SQL", "Risk Management"]
    """
    years = _estimate_years_experience(resume_text)
    seniority = extract_seniority(resume_text, years)
    industries = extract_industries(resume_text)
    skills = extract_skill_names(resume_text)

    return {
        "years_experience": years,
        "seniority_level": seniority["seniority_level"],
        "seniority_method": seniority["method"],
        "industries": [i["industry"] for i in industries],
        "skills": skills,
    }
