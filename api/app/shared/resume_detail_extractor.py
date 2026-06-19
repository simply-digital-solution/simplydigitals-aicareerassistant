"""
Resume detail extractor — LLM-based.

Extracts 6 categories from resume text in a single LLM call:
  - target_industries (list[str])
  - target_roles (list[str])
  - skills (list[str])
  - education (list[{degree, institution, year}])
  - certifications (list[{name, issuer, issued_date, expiry_date}])
  - contact ({phone, email})

All fields default to empty list / empty string if not found — never raises.
"""
from __future__ import annotations

import json
import re

_SYSTEM_PROMPT = """You are a resume parser. Extract structured information from the resume text.
Return ONLY valid JSON matching the schema below. No markdown, no explanation, no commentary.

Schema:
{
  "target_industries": ["string"],
  "target_roles": ["string"],
  "skills": ["string"],
  "education": [{"degree": "string", "institution": "string", "year": "string"}],
  "certifications": [{"name": "string", "issuer": "string", "issued_date": "string", "expiry_date": "string"}],
  "contact": {"phone": "string", "email": "string"}
}

Rules:
- target_industries: 1-5 industries this person has worked in or is suited for
- target_roles: 3-7 job titles this person could reasonably apply for
- skills: all technical and professional skills mentioned, no duplicates
- education: degree name, institution name, graduation year (or empty string if unknown)
- certifications: use empty string for missing issued_date or expiry_date
- contact.phone: include country code if present, e.g. +6590673055; empty string if not found
- contact.email: empty string if not found
- Return empty arrays/strings for any field not found — never omit a key"""

_USER_PROMPT = """Extract all details from this resume:

{resume_text}

Return ONLY the JSON object:"""


def _empty_result() -> dict:
    return {
        "target_industries": [],
        "target_roles": [],
        "skills": [],
        "education": [],
        "certifications": [],
        "contact": {"phone": "", "email": ""},
    }


def _parse_response(raw: str) -> dict:
    """Extract JSON object from LLM response, tolerating markdown fences."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", raw).strip()
    # Find first { ... } block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return _empty_result()
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return _empty_result()

    result = _empty_result()

    for key in ("target_industries", "target_roles", "skills"):
        val = data.get(key)
        if isinstance(val, list):
            result[key] = [str(v).strip() for v in val if v and str(v).strip()]

    edu_raw = data.get("education")
    if isinstance(edu_raw, list):
        for entry in edu_raw:
            if isinstance(entry, dict):
                result["education"].append({
                    "degree": str(entry.get("degree", "")).strip(),
                    "institution": str(entry.get("institution", "")).strip(),
                    "year": str(entry.get("year", "")).strip(),
                })

    cert_raw = data.get("certifications")
    if isinstance(cert_raw, list):
        for entry in cert_raw:
            if isinstance(entry, dict):
                result["certifications"].append({
                    "name": str(entry.get("name", "")).strip(),
                    "issuer": str(entry.get("issuer", "")).strip(),
                    "issued_date": str(entry.get("issued_date", "")).strip(),
                    "expiry_date": str(entry.get("expiry_date", "")).strip(),
                })

    contact = data.get("contact")
    if isinstance(contact, dict):
        result["contact"]["phone"] = str(contact.get("phone", "")).strip()
        result["contact"]["email"] = str(contact.get("email", "")).strip()

    return result


async def extract_resume_details(resume_text: str, api_client) -> dict:
    """
    Call LLM to extract all 6 categories from the resume.
    Returns _empty_result() structure on any failure — never raises.
    """
    snippet = resume_text[:6000]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT.format(resume_text=snippet)},
    ]
    try:
        raw, _ = await api_client._call(messages)
        return _parse_response(raw)
    except Exception:
        return _empty_result()
