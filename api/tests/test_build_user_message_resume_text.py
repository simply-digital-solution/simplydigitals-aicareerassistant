"""
Unit tests for _build_user_message() including the candidate's full
resume_text in the scoring prompt.

Regression coverage: the scoring LLM previously only ever saw a flat
extracted skills list (profile.skills), never the resume itself, so any
experience/domain the extraction step missed (e.g. "FX" appearing
throughout the resume prose but never captured as a discrete skill tag)
was invisible to the scorer — producing risks like "no FX-specific work"
despite extensive FX content in the actual resume.
"""
from app.modules.agents.research_agent import _build_user_message


def _make_profile(resume_text=None, core_skills=None):
    return {
        "core_skills": core_skills or [],
        "resume_text": resume_text,
        "background": {"years_experience": 5},
        "targets": {"locations": []},
        "compensation": {},
        "rules": {},
    }


def test_resume_text_included_in_message():
    profile = _make_profile(resume_text="Delivered FX options trading platform at Citibank.")

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "Full resume" in message
    assert "Delivered FX options trading platform at Citibank." in message


def test_resume_text_omitted_when_empty():
    profile = _make_profile(resume_text="")

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "Full resume" not in message


def test_resume_text_omitted_when_missing_key():
    profile = _make_profile()
    del profile["resume_text"]

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "Full resume" not in message


def test_resume_text_whitespace_only_treated_as_empty():
    profile = _make_profile(resume_text="   \n\t  ")

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "Full resume" not in message


def test_core_skills_line_still_present_alongside_resume_text():
    profile = _make_profile(resume_text="Full career history here.", core_skills=["Python", "SQL"])

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "- Core skills: Python, SQL" in message
    assert "Full career history here." in message
