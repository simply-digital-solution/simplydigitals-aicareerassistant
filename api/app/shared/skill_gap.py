"""
Title skill gap analyser.

After a research run, collects JD keywords per matched target title,
calls the LLM once per title to distill the top required skills,
and persists them to title_skill_map.

Gap analysis: required_skills vs profile.skills → have / missing.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Persist / retrieve
# ---------------------------------------------------------------------------

async def save_title_skills(
    db: AsyncSession,
    user_id: int,
    title: str,
    required_skills: list[str],
    source_keywords: list[str],
) -> None:
    await db.execute(
        text("""
            INSERT INTO title_skill_map (user_id, title, required_skills, source_keywords, last_updated)
            VALUES (:uid, :title, :skills, :keywords, :now)
            ON CONFLICT(user_id, title) DO UPDATE SET
                required_skills = excluded.required_skills,
                source_keywords = excluded.source_keywords,
                last_updated    = excluded.last_updated
        """),
        {
            "uid": user_id,
            "title": title,
            "skills": json.dumps(required_skills),
            "keywords": json.dumps(source_keywords),
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )
    await db.commit()


async def get_all_title_skills(
    db: AsyncSession,
    user_id: int,
) -> list[dict]:
    rows = await db.execute(
        text("""
            SELECT title, required_skills, source_keywords, last_updated
            FROM title_skill_map
            WHERE user_id = :uid
            ORDER BY title
        """),
        {"uid": user_id},
    )
    result = []
    for row in rows.mappings():
        result.append({
            "title": row["title"],
            "required_skills": json.loads(row["required_skills"]) if row["required_skills"] else [],
            "source_keywords": json.loads(row["source_keywords"]) if row["source_keywords"] else [],
            "last_updated": row["last_updated"],
        })
    return result


# ---------------------------------------------------------------------------
# LLM distillation — one call per title
# ---------------------------------------------------------------------------

async def distill_required_skills(
    title: str,
    raw_keywords: list[str],
    api_client,
) -> list[str]:
    """
    Ask the LLM to distill a clean list of required skills for `title`
    from the raw JD keywords collected across job postings.
    Returns a deduplicated list of up to 15 skills.
    """
    if not raw_keywords:
        return []

    kw_text = ", ".join(dict.fromkeys(k.lower() for k in raw_keywords))
    messages = [
        {
            "role": "system",
            "content": "You are a job market analyst. Return only valid JSON arrays, no explanation.",
        },
        {
            "role": "user",
            "content": (
                f'Based on these keywords from real job postings for "{title}":\n\n{kw_text}\n\n'
                f"Return a JSON array of the top 15 skills actually required for this role. "
                f"Rules:\n"
                f"- Use the shortest canonical name: 'Agile' not 'Agile Methodology', 'JIRA' not 'Jira Software', 'CI/CD' not 'Continuous Integration/Continuous Deployment'\n"
                f"- Single technology or concept per entry, no compound phrases\n"
                f"- Exclude generic soft skills like 'communication' or 'teamwork'\n"
                f"Return ONLY a JSON array, no explanation."
            ),
        },
    ]

    try:
        raw, _ = await api_client._call(messages)
        match = re.search(r'\[.*?\]', raw.strip(), re.DOTALL)
        if match:
            skills = json.loads(match.group())
            seen: set[str] = set()
            deduped: list[str] = []
            for s in skills:
                if isinstance(s, str) and s.strip():
                    key = s.strip().lower()
                    if key not in seen:
                        seen.add(key)
                        deduped.append(s.strip())
            return deduped[:15]
    except Exception:
        pass

    return []


# ---------------------------------------------------------------------------
# Skill implication map
# "if you have X, you implicitly cover Y"
# ---------------------------------------------------------------------------

_IMPLIES: dict[str, list[str]] = {
    # Agile / Scrum covers all core ceremonies and artefacts
    "agile": [
        "user stories", "backlog", "backlog management", "backlog grooming",
        "sprint planning", "sprint", "retrospectives", "burndown charts",
        "velocity", "story points", "acceptance criteria", "definition of done",
        "daily standup", "scrum ceremonies", "iteration planning",
        "uat", "user acceptance testing", "release management",
    ],
    "scrum": [
        "user stories", "backlog", "backlog management", "backlog grooming",
        "sprint planning", "sprint", "retrospectives", "burndown charts",
        "velocity", "story points", "scrum ceremonies",
        "uat", "user acceptance testing",
    ],
    "product owner": [
        "user stories", "backlog", "backlog management", "backlog grooming",
        "sprint planning", "prioritization", "release planning",
        "stakeholder management", "requirements gathering",
        "uat", "user acceptance testing", "kpis",
    ],
    "product management": [
        "user stories", "backlog", "prioritization", "roadmap",
        "stakeholder management", "requirements gathering", "kpis",
        "uat", "user acceptance testing",
    ],
    "jira": ["backlog", "sprint planning", "issue tracking", "kanban"],
    "kanban": ["backlog", "wip limits", "flow management"],
    # Market risk covers related sub-disciplines
    "market risk": [
        "var", "stress testing", "sensitivities", "greeks",
        "pnl attribution", "p&l attribution", "position management",
    ],
    "p&l attribution": ["pnl attribution", "p&l", "profit and loss"],
    "trade lifecycle": [
        "trade capture", "trade reconciliation", "settlements",
        "front-to-back", "order management",
    ],
    "murex": ["mxml", "trade capture", "risk systems", "pricing models"],
    # DevOps / CI/CD
    "devops": ["ci/cd", "infrastructure as code", "release management", "deployment"],
    "ci/cd": ["release management", "deployment", "automated testing"],
    # Regulatory / compliance
    "bcbs 239": ["regulatory reporting", "risk data aggregation"],
    "regulatory reporting": ["compliance reporting", "data governance"],
    # Leadership
    "team management": [
        "mentoring", "performance management", "hiring", "stakeholder management",
    ],
    "leadership": ["stakeholder management", "mentoring", "team management"],
    # SQL covers adjacent query skills
    "sql": ["t-sql", "pl/sql", "database queries", "data querying"],
    # Python covers scripting generics
    "python": ["scripting", "automation", "data processing"],
    # AWS covers cloud generics
    "aws": ["cloud", "cloud computing", "cloud infrastructure"],
    # Stakeholder management
    "stakeholder management": ["requirements gathering", "executive communication"],
    # Project / programme management
    "pmp": ["project management", "programme management", "pmo"],
    "project management": ["requirements gathering", "release planning", "prioritization"],
}


def _expand_profile(profile_skills_lower: set[str]) -> set[str]:
    """Add all implied skills to the profile set."""
    expanded = set(profile_skills_lower)
    for skill in list(profile_skills_lower):
        for trigger, implied in _IMPLIES.items():
            if trigger in skill or skill in trigger:
                expanded.update(implied)
    return expanded


# ---------------------------------------------------------------------------
# Gap analysis (pure function — no DB needed)
# ---------------------------------------------------------------------------

def _skill_matches(required: str, profile_skills_lower: set[str]) -> bool:
    """
    Fuzzy match: a required skill is considered covered if any profile skill
    is a substring of it or vice versa.
    Examples:
      "agile" matches "agile methodology"
      "agile methodology" matches "agile"
      "jira" matches "jira software"
      "ci/cd" matches "ci/cd & devops"
    """
    req = required.strip().lower()
    if req in profile_skills_lower:
        return True
    for ps in profile_skills_lower:
        if ps in req or req in ps:
            return True
    return False


def compute_gap(
    required_skills: list[str],
    profile_skills: list[str],
) -> dict:
    """
    Compare required skills against profile skills using fuzzy substring matching.

    Returns:
        have    : list[str]  — required skills covered by profile
        missing : list[str]  — required skills not covered
        coverage: float      — 0.0–1.0
    """
    profile_lower = _expand_profile({s.strip().lower() for s in profile_skills})
    have: list[str] = []
    missing: list[str] = []

    for skill in required_skills:
        if _skill_matches(skill, profile_lower):
            have.append(skill)
        else:
            missing.append(skill)

    total = len(required_skills)
    coverage = len(have) / total if total > 0 else 0.0

    return {
        "have": have,
        "missing": missing,
        "coverage": round(coverage, 2),
    }


# ---------------------------------------------------------------------------
# Seed required skills from title name alone (no JD keywords)
# ---------------------------------------------------------------------------

async def seed_required_skills(
    title: str,
    api_client,
) -> list[str]:
    """
    Ask the LLM to generate required skills for a title using its training
    knowledge of the job market — used when no JD keywords are available yet.
    """
    messages = [
        {
            "role": "system",
            "content": "You are a job market analyst. Return only valid JSON arrays, no explanation.",
        },
        {
            "role": "user",
            "content": (
                f'You are an expert in technology and financial services hiring.\n\n'
                f'List the top 15 skills typically required for the role: "{title}"\n\n'
                f'Rules:\n'
                f'- Focus on TECHNOLOGY skills if this is a technology role (systems, platforms, tools, languages)\n'
                f'- Focus on DOMAIN skills if this is a functional role (risk frameworks, regulations, methodologies)\n'
                f'- Use shortest canonical names: "Python" not "Python programming", "Agile" not "Agile Methodology"\n'
                f'- Single technology or concept per entry, no compound phrases\n'
                f'- Exclude generic soft skills like "communication" or "teamwork"\n'
                f'- Base this on real job postings, not textbook definitions\n'
                f'Return ONLY a JSON array of strings, no explanation.'
            ),
        },
    ]

    try:
        raw, _ = await api_client._call(messages)
        match = re.search(r'\[.*?\]', raw.strip(), re.DOTALL)
        if match:
            skills = json.loads(match.group())
            seen: set[str] = set()
            deduped: list[str] = []
            for s in skills:
                if isinstance(s, str) and s.strip():
                    key = s.strip().lower()
                    if key not in seen:
                        seen.add(key)
                        deduped.append(s.strip())
            return deduped[:15]
    except Exception:
        pass

    return []


# ---------------------------------------------------------------------------
# Main entry point — called after research completes
# ---------------------------------------------------------------------------

async def update_title_skills_from_research(
    db: AsyncSession,
    user_id: int,
    target_titles: list[str],
    opportunities: list[dict],   # ResearchOutput.opportunities as dicts
    api_client,
) -> None:
    """
    Group job keywords by matched target title, distill required skills
    via LLM, and persist to title_skill_map.

    Matching: a job's `role` field is matched to target titles by
    substring containment (case-insensitive).
    """
    if not target_titles or not opportunities:
        return

    # Collect keywords per title
    title_keywords: dict[str, list[str]] = {t: [] for t in target_titles}

    for opp in opportunities:
        role = (opp.get("role") or "").lower()
        keywords = opp.get("key_keywords") or []
        for title in target_titles:
            # Match if either contains the other (handles "Risk Manager" ↔ "Risk Technology Lead")
            title_words = set(title.lower().split())
            role_words = set(role.split())
            if title_words & role_words:  # any word overlap
                title_keywords[title].extend(keywords)

    # Distill and persist each title that has keywords
    import asyncio
    async def process_title(title: str) -> None:
        kws = title_keywords.get(title, [])
        if not kws:
            return
        skills = await distill_required_skills(title, kws, api_client)
        if skills:
            await save_title_skills(db, user_id, title, skills, list(dict.fromkeys(kws)))

    await asyncio.gather(*[process_title(t) for t in target_titles])
