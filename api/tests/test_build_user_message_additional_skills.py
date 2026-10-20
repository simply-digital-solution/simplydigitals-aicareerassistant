"""
Unit tests for _build_user_message()'s handling of profile['additional_skills'] —
manually curated skills kept separate from resume-derived profile['core_skills'],
sent to the scoring LLM as their own labeled line.
"""
from app.modules.agents.research_agent import _build_user_message


def _make_profile(core_skills=None, additional_skills=None):
    return {
        "core_skills": core_skills or [],
        "additional_skills": additional_skills or [],
        "background": {"years_experience": 5},
        "targets": {"locations": []},
        "compensation": {},
        "rules": {},
    }


def test_additional_skills_included_as_separate_labeled_line():
    profile = _make_profile(
        core_skills=["Python", "SQL"],
        additional_skills=["Negotiation", "Public Speaking"],
    )

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "- Core skills: Python, SQL" in message
    assert "- Additional skills (self-reported): Negotiation, Public Speaking" in message


def test_additional_skills_line_omitted_when_empty():
    profile = _make_profile(core_skills=["Python"], additional_skills=[])

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "Additional skills" not in message


def test_additional_skills_line_omitted_when_key_missing():
    profile = _make_profile(core_skills=["Python"])
    del profile["additional_skills"]

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "Additional skills" not in message


def test_core_skills_unaffected_by_additional_skills_presence():
    profile = _make_profile(core_skills=["Python"], additional_skills=["Negotiation"])

    message = _build_user_message(profile, job_postings=[], search_filters={})

    assert "- Core skills: Python" in message
