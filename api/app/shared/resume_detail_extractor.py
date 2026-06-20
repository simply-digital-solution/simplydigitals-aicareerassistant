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

import asyncio
import json
import re

_SYSTEM_PROMPT = """You are a resume parser. Extract structured information from the resume text.
Return ONLY valid JSON matching the schema below. No markdown, no explanation, no commentary.

Schema:
{
  "years_experience": number or null,
  "seniority_level": "string",
  "target_industries": ["string"],
  "target_roles": ["string"],
  "skills": ["string"],
  "education": [{"degree": "string", "institution": "string", "year": "string"}],
  "certifications": [{"name": "string", "issuer": "string", "issued_date": "string", "expiry_date": "string"}],
  "contact": {"phone_country_code": "string", "phone_local": "string", "email": "string"}
}

Rules:
- years_experience: total years of professional experience as an integer, or null if cannot be determined
- seniority_level: one of "junior", "mid", "senior", "lead", "principal", "director", "vp", "executive" — infer from titles, responsibilities, and years
- target_industries: 1-5 industries this person has worked in or is suited for
- target_roles: 3-7 job titles this person could reasonably apply for
- skills: all technical and professional skills mentioned, no duplicates
- education: degree name, institution name, graduation year (or empty string if unknown)
- certifications: use empty string for missing issued_date or expiry_date
- contact.phone_country_code: the international dialling prefix including + sign, e.g. "+65", "+1", "+44"; empty string if not found
- contact.phone_local: the local number without country code, e.g. "90673055"; empty string if not found
- contact.email: empty string if not found
- Return empty arrays/strings/null for any field not found — never omit a key"""

_USER_PROMPT = """Extract all details from this resume:

{resume_text}

Return ONLY the JSON object:"""


def _empty_result() -> dict:
    return {
        "years_experience": None,
        "seniority_level": "",
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

    yoe = data.get("years_experience")
    if isinstance(yoe, (int, float)) and yoe >= 0:
        result["years_experience"] = int(yoe)

    seniority = str(data.get("seniority_level", "")).strip().lower()
    valid_levels = {"junior", "mid", "senior", "lead", "principal", "director", "vp", "executive"}
    if seniority in valid_levels:
        result["seniority_level"] = seniority

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
        code = str(contact.get("phone_country_code", "")).strip()
        local = str(contact.get("phone_local", "")).strip()
        # Combine as "+65 90673055" (space-separated for reliable display splitting)
        if code and local:
            result["contact"]["phone"] = f"{code} {local}"
        elif local:
            result["contact"]["phone"] = local
        result["contact"]["email"] = str(contact.get("email", "")).strip()

    return result


LLM_EXTRACTION_TIMEOUT = 30.0


async def extract_resume_details(resume_text: str, api_client) -> dict:
    """
    Call LLM to extract all fields from the resume.
    Times out after 30s and returns _empty_result() on any failure — never raises.
    """
    snippet = resume_text[:12000]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT.format(resume_text=snippet)},
    ]
    try:
        raw, _ = await asyncio.wait_for(
            api_client._call(messages),
            timeout=LLM_EXTRACTION_TIMEOUT,
        )
        return _parse_response(raw)
    except Exception:
        return _empty_result()


_DEDUP_SYSTEM_PROMPT = """You are a data deduplication assistant. You will receive a JSON array of certification objects.
Some entries refer to the same certification but use different name formats (e.g. "PMP" and "Project Management Professional (PMP)").
Return ONLY a valid JSON array with duplicates removed. Rules:
- When two entries refer to the same certification (same cert, same issuer), keep ONE entry
- For the kept entry: use the most complete/descriptive name (prefer the full name over abbreviation)
- Fill in any missing fields (issued_date, expiry_date) from the duplicate if available
- If entries are genuinely different certifications, keep both
- Return ONLY the JSON array, no explanation, no markdown"""

_DEDUP_USER_PROMPT = """Deduplicate this certification list. Return ONLY the JSON array:

{certs_json}"""


async def deduplicate_certifications(entries: list[dict], api_client) -> list[dict]:
    """
    Use the LLM to deduplicate a certification list by semantic equivalence.
    Falls back to the original list on any failure — never raises.
    """
    if len(entries) <= 1:
        return entries

    certs_json = json.dumps(entries, indent=2)
    messages = [
        {"role": "system", "content": _DEDUP_SYSTEM_PROMPT},
        {"role": "user", "content": _DEDUP_USER_PROMPT.format(certs_json=certs_json)},
    ]
    try:
        raw, _ = await api_client._call(messages)
        text = re.sub(r"```(?:json)?", "", raw).strip()
        # Find the JSON array
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return entries
        parsed = json.loads(match.group())
        if not isinstance(parsed, list):
            return entries
        # Validate each entry has required keys
        result = []
        for item in parsed:
            if isinstance(item, dict) and item.get("name"):
                result.append({
                    "name": str(item.get("name", "")).strip(),
                    "issuer": str(item.get("issuer", "")).strip(),
                    "issued_date": str(item.get("issued_date", "")).strip(),
                    "expiry_date": str(item.get("expiry_date", "")).strip(),
                })
        return result if result else entries
    except Exception:
        return entries
