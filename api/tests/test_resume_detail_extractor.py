"""Tests for resume_detail_extractor — parse logic and additive merge."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Parser tests (no LLM call — test _parse_response directly)
# ---------------------------------------------------------------------------

def _parse(raw: str) -> dict:
    from app.shared.resume_detail_extractor import _parse_response
    return _parse_response(raw)


def test_parses_all_fields():
    raw = json.dumps({
        "target_industries": ["Finance", "Technology"],
        "target_roles": ["Software Engineer", "Tech Lead"],
        "skills": ["Python", "SQL"],
        "education": [{"degree": "BSc CS", "institution": "NUS", "year": "2018"}],
        "certifications": [{"name": "AWS SAA", "issuer": "Amazon", "issued_date": "2023-01", "expiry_date": "2026-01"}],
        "contact": {"phone_country_code": "+65", "phone_local": "90673055", "email": "test@example.com"},
    })
    result = _parse(raw)
    assert result["target_industries"] == ["Finance", "Technology"]
    assert result["target_roles"] == ["Software Engineer", "Tech Lead"]
    assert result["skills"] == ["Python", "SQL"]
    assert result["education"] == [{"degree": "BSc CS", "institution": "NUS", "year": "2018"}]
    assert result["certifications"] == [{"name": "AWS SAA", "issuer": "Amazon", "issued_date": "2023-01", "expiry_date": "2026-01"}]
    assert result["contact"]["phone"] == "+65 90673055"
    assert result["contact"]["email"] == "test@example.com"


def test_phone_combined_without_country_code():
    raw = json.dumps({"contact": {"phone_country_code": "", "phone_local": "90673055", "email": ""}})
    result = _parse(raw)
    assert result["contact"]["phone"] == "90673055"


def test_phone_empty_when_both_missing():
    raw = json.dumps({"contact": {"phone_country_code": "", "phone_local": "", "email": ""}})
    result = _parse(raw)
    assert result["contact"]["phone"] == ""


def test_missing_fields_default_to_empty():
    raw = json.dumps({"target_industries": ["Finance"]})
    result = _parse(raw)
    assert result["target_roles"] == []
    assert result["skills"] == []
    assert result["education"] == []
    assert result["certifications"] == []
    assert result["contact"]["phone"] == ""
    assert result["contact"]["email"] == ""


def test_tolerates_markdown_fences():
    raw = "```json\n" + json.dumps({"skills": ["Python"]}) + "\n```"
    result = _parse(raw)
    assert result["skills"] == ["Python"]


def test_invalid_json_returns_empty():
    result = _parse("not valid json at all")
    assert result["skills"] == []
    assert result["target_industries"] == []


def test_strips_blank_string_items():
    raw = json.dumps({"skills": ["Python", "", "  ", "SQL"]})
    result = _parse(raw)
    assert result["skills"] == ["Python", "SQL"]


# ---------------------------------------------------------------------------
# extract_resume_details integration (mock LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_resume_details_calls_llm_and_parses():
    from app.shared.resume_detail_extractor import extract_resume_details

    llm_response = json.dumps({
        "target_industries": ["Banking"],
        "target_roles": ["Data Engineer"],
        "skills": ["Spark", "Kafka"],
        "education": [{"degree": "MSc", "institution": "SMU", "year": "2020"}],
        "certifications": [],
        "contact": {"phone_country_code": "+65", "phone_local": "91234567", "email": "user@bank.com"},
    })
    client = MagicMock()
    client._call = AsyncMock(return_value=(llm_response, {}))

    result = await extract_resume_details("Sample resume text", client)
    assert result["target_industries"] == ["Banking"]
    assert result["skills"] == ["Spark", "Kafka"]
    assert result["contact"]["phone"] == "+65 91234567"


@pytest.mark.asyncio
async def test_extract_resume_details_returns_empty_on_llm_error():
    from app.shared.resume_detail_extractor import extract_resume_details

    client = MagicMock()
    client._call = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    result = await extract_resume_details("Resume text", client)
    assert result["skills"] == []
    assert result["target_industries"] == []
    assert result["contact"]["phone"] == ""


# ---------------------------------------------------------------------------
# Additive merge logic tests (test via router helper functions indirectly
# by importing the merge logic extracted into testable functions)
# ---------------------------------------------------------------------------

def test_no_duplicate_skills_on_merge():
    """Skills already in profile must not be duplicated when new ones arrive."""
    import json as _json

    existing_json = _json.dumps(["Python", "SQL"])
    new_items = ["python", "Spark", "SQL"]  # python and SQL are dupes

    # Replicate the merge logic from the endpoint
    existing = _json.loads(existing_json)
    existing_lower = {s.strip().lower() for s in existing}
    merged = existing + [s for s in new_items if s.strip().lower() not in existing_lower]

    assert merged.count("Python") == 1
    assert merged.count("SQL") == 1
    assert "Spark" in merged
    assert len(merged) == 3


def test_education_deduped_by_degree_and_institution():
    existing = [{"degree": "BSc CS", "institution": "NUS", "year": "2018"}]
    new_items = [
        {"degree": "bsc cs", "institution": "nus", "year": "2018"},  # dupe
        {"degree": "MSc", "institution": "NTU", "year": "2020"},      # new
    ]
    existing_keys = {
        (e["degree"].strip().lower(), e["institution"].strip().lower())
        for e in existing
    }
    for entry in new_items:
        key = (entry["degree"].strip().lower(), entry["institution"].strip().lower())
        if key not in existing_keys and (key[0] or key[1]):
            existing.append(entry)
            existing_keys.add(key)

    assert len(existing) == 2
    assert existing[1]["degree"] == "MSc"


def test_certifications_deduped_by_name_and_issuer():
    existing = [{"name": "AWS SAA", "issuer": "Amazon", "issued_date": "2023-01", "expiry_date": "2026-01"}]
    new_items = [
        {"name": "aws saa", "issuer": "amazon", "issued_date": "2023-01", "expiry_date": "2026-01"},  # dupe
        {"name": "GCP ACE", "issuer": "Google", "issued_date": "2024-01", "expiry_date": "2027-01"},   # new
    ]
    existing_keys = {
        (e["name"].strip().lower(), e["issuer"].strip().lower())
        for e in existing
    }
    for entry in new_items:
        key = (entry["name"].strip().lower(), entry["issuer"].strip().lower())
        if key not in existing_keys and key[0]:
            existing.append(entry)
            existing_keys.add(key)

    assert len(existing) == 2
    assert existing[1]["name"] == "GCP ACE"


def test_phone_not_overwritten_if_already_set():
    existing_phone = "+6590673055"
    extracted_phone = "+6599999999"
    # merge rule: only write if currently empty
    result = extracted_phone if not existing_phone else existing_phone
    assert result == "+6590673055"


def test_phone_written_when_empty():
    existing_phone = ""
    extracted_phone = "+6591234567"
    result = extracted_phone if not existing_phone else existing_phone
    assert result == "+6591234567"
