"""
Target title extractor — LLM-based.

Replaces the BERT zero-shot approach. The LLM reads the full resume and infers
target job titles with explicit reasoning about whether the candidate is a
technology builder or a functional/business manager.

Key prompt rules:
- Distinguish "built the risk system" (tech role) from "managed the risk function" (functional role)
- Look at verbs: designed/architected/implemented → tech track
- Look at reporting lines and team composition in the resume
- Never infer functional ownership titles (Market Risk Manager, Risk Manager, Regulatory Reporting Manager)
  unless the resume explicitly shows the person owned the P&L or business function, not just the technology
"""
import json
import re
import asyncio
from typing import Optional


_TOP_N = 5

_SYSTEM_PROMPT = """You are a career coach specialising in technology and financial services.
Your task is to infer the most relevant TARGET JOB TITLES for a candidate based on their resume.

CRITICAL DISTINCTION — you must get this right:
- A candidate who BUILT a market risk system is a TECHNOLOGIST targeting roles like:
  "Risk Technology Lead", "Capital Markets Technology Lead", "Trading Systems Manager"
- A candidate who MANAGED the market risk function (owned P&L, approved positions, set limits) is a FUNCTIONAL MANAGER targeting:
  "Market Risk Manager", "Chief Risk Officer"

To determine which track applies, look at:
1. VERBS in bullet points: built / designed / architected / implemented / engineered / developed → TECH TRACK
   managed risk / approved / set limits / owned P&L / reported to CRO → FUNCTIONAL TRACK
2. TEAM: "led a team of developers/engineers" → TECH TRACK
   "led a team of risk analysts/quants" → FUNCTIONAL TRACK
3. DELIVERABLES: systems, platforms, pipelines, APIs → TECH TRACK
   limits frameworks, risk reports, regulatory submissions → FUNCTIONAL TRACK

Return ONLY a JSON array of strings. No explanation, no markdown, no commentary.
Return exactly the job titles, ordered by relevance (most relevant first).
Maximum 5 titles."""

_USER_PROMPT_TEMPLATE = """Based on the resume below, infer the top {top_n} target job titles for this candidate.

Rules:
- Return technology-track titles if the candidate built systems/platforms (most likely)
- Return functional titles ONLY if the resume explicitly shows business function ownership (P&L, limits, approvals)
- Use real market-standard job title names that would appear in job postings
- Be specific: "Risk Technology Lead" is better than "Technology Manager"
- Do not invent hybrid titles that don't exist in job markets
- Return ONLY a JSON array of strings, e.g.: ["Title One", "Title Two", "Title Three"]

Resume:
{resume_text}

Return ONLY the JSON array:"""


async def extract_target_titles(
    resume_text: str,
    top_n: int = _TOP_N,
    api_client=None,
) -> list[str]:
    """
    Infer target job titles from resume text using the LLM.

    Falls back to regex-based heuristic if the LLM call fails.
    """
    if api_client is not None:
        try:
            return await _llm_extract(resume_text, top_n, api_client)
        except Exception:
            pass

    # Fallback: lightweight heuristic if no client available
    return _heuristic_extract(resume_text, top_n)


async def _llm_extract(resume_text: str, top_n: int, api_client) -> list[str]:
    # Truncate to ~4000 chars to keep token cost low while retaining enough context
    snippet = resume_text[:4000]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _USER_PROMPT_TEMPLATE.format(
                top_n=top_n,
                resume_text=snippet,
            ),
        },
    ]
    raw, _ = await api_client._call(messages)
    match = re.search(r'\[.*?\]', raw.strip(), re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in LLM response")
    titles = json.loads(match.group())
    if not isinstance(titles, list):
        raise ValueError("LLM response is not a list")
    return [t.strip() for t in titles if isinstance(t, str) and t.strip()][:top_n]


# ---------------------------------------------------------------------------
# Lightweight heuristic fallback (no LLM, no BERT)
# ---------------------------------------------------------------------------

_TECH_SIGNALS = re.compile(
    r'\b(built|designed|architected|implemented|developed|engineered|deployed|'
    r'migrated|integrated|automated|led\s+(?:the\s+)?(?:build|development|design|implementation))\b',
    re.IGNORECASE,
)

_DOMAIN_SIGNALS = {
    "risk_technology": re.compile(
        r'\b(market risk|credit risk|risk system|risk platform|risk technology|'
        r'p&l|pnl|var|stress test|murex|calypso|regulatory report)\b',
        re.IGNORECASE,
    ),
    "trading_systems": re.compile(
        r'\b(trading system|trade lifecycle|order management|fix protocol|'
        r'front.?to.?back|settlement|trade capture)\b',
        re.IGNORECASE,
    ),
    "data_engineering": re.compile(
        r'\b(data pipeline|etl|data warehouse|spark|kafka|airflow|dbt)\b',
        re.IGNORECASE,
    ),
    "product": re.compile(
        r'\b(product owner|product manager|roadmap|backlog|user stor)\b',
        re.IGNORECASE,
    ),
}

_FALLBACK_MAP = {
    "risk_technology": ["Risk Technology Lead", "Capital Markets Technology Lead"],
    "trading_systems": ["Trading Systems Manager", "Capital Markets Technology Lead"],
    "data_engineering": ["Data Engineer", "Head of Data"],
    "product": ["Product Manager", "Product Owner"],
}
_DEFAULT_FALLBACK = ["Technology Lead", "Engineering Manager"]


def _heuristic_extract(resume_text: str, top_n: int) -> list[str]:
    tech_score = len(_TECH_SIGNALS.findall(resume_text))
    results: list[str] = []
    seen: set[str] = set()

    for domain, pattern in _DOMAIN_SIGNALS.items():
        if pattern.search(resume_text):
            for title in _FALLBACK_MAP.get(domain, []):
                if title not in seen:
                    seen.add(title)
                    results.append(title)

    if not results:
        results = list(_DEFAULT_FALLBACK)

    return results[:top_n]
